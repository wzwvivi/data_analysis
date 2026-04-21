# -*- coding: utf-8 -*-
"""
飞控事件分析规则引擎（FCC Event Analysis）

基于状态机模式，从 pcap 中 FCC 关键端口的轻量解码，识别：
  1. 主飞控异常（无主/双主/切换/抖动）
  2. 三机传感器选择分歧（IRS/RA 一致性）
  3. 主飞控与其他飞控不一致
  4. 飞控判断的通道故障（IRS/RA 故障开始/恢复）
  5. 选择与故障状态不一致
  6. 因果链事件

端口与字节偏移（TSN 头 8B 后的结构体数据）：
  飞控状态帧  9001/9002/9003  byte1 = 表决结果 (bit0=FCC1, bit1=FCC2, bit2=FCC3)
  飞控通道选择 9011/9012/9013  byte1 = IRS选择(0/1/2), byte2 = RA选择(0/1)
  飞控通道故障 9021/9022/9023  byte1 = IRS故障(bit0-2), byte2 = RA故障(bit0-1)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

# 所有 payload 内部 byte offset 集中在 payload_layouts（非 ICD 数据）。
from ..payload_layouts import (
    TSN_HEADER_LEN,
    FCC_STATUS_VOTE_OFFSET,
    FCC_CHANNEL_IRS_SEL_OFFSET,
    FCC_CHANNEL_RA_SEL_OFFSET,
    FCC_FAULT_IRS_BITMAP_OFFSET,
    FCC_FAULT_RA_BITMAP_OFFSET,
)

STATUS_PORTS = {9001: "FCC1", 9002: "FCC2", 9003: "FCC3"}
CHANNEL_PORTS = {9011: "FCC1", 9012: "FCC2", 9013: "FCC3"}
FAULT_PORTS = {9021: "FCC1", 9022: "FCC2", 9023: "FCC3"}

IRS_NAME = {0: "IRS1", 1: "IRS2", 2: "IRS3"}
RA_NAME = {0: "RA1", 1: "RA2"}

JITTER_WINDOW_SEC = 10.0
JITTER_THRESHOLD = 4

FAULT_SWITCH_TIMEOUT_SEC = 2.0
RECOVERY_RESELECT_TIMEOUT_SEC = 5.0

CAUSAL_WINDOW_SEC = 3.0


# ── dataclasses compatible with the existing persist layer ──────────────

@dataclass
class _FccCheckItem:
    sequence: int
    name: str
    category: str
    description: str
    port: int = 0
    wireshark_filter: str = ""


@dataclass
class FccCheckResult:
    check_item: _FccCheckItem
    event_time: Optional[str] = None
    event_description: str = ""
    period_expected: str = ""
    period_actual: str = ""
    period_analysis: str = ""
    period_result: str = "na"
    content_expected: str = ""
    content_actual: str = ""
    content_analysis: str = ""
    content_result: str = "na"
    response_expected: str = ""
    response_actual: str = ""
    response_analysis: str = ""
    response_result: str = "na"
    overall_result: str = "pass"
    evidence_data: Dict = field(default_factory=dict)


@dataclass
class FccTimelineEvent:
    timestamp: float
    time_str: str
    device: str
    port: int
    event_type: str
    event_name: str
    event_description: str
    raw_data_hex: Optional[str] = None
    field_values: Optional[Dict] = None
    related_check_sequence: Optional[int] = None


# ── helpers ─────────────────────────────────────────────────────────────

def _ts_to_str(ts: float) -> str:
    try:
        return datetime.utcfromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return str(ts)


def _decode_payload(raw_hex: str) -> Optional[bytes]:
    """Return application-level bytes after TSN header, or None if too short."""
    try:
        full = bytes.fromhex(raw_hex)
    except (ValueError, TypeError):
        return None
    if len(full) <= TSN_HEADER_LEN:
        return None
    return full[TSN_HEADER_LEN:]


def _mains_from_vote(vote: int) -> List[str]:
    mains: List[str] = []
    if vote & 0x01:
        mains.append("FCC1")
    if vote & 0x02:
        mains.append("FCC2")
    if vote & 0x04:
        mains.append("FCC3")
    return mains


# ── FccChecksheet ───────────────────────────────────────────────────────

class FccChecksheet:
    """飞控事件分析规则引擎。"""

    def __init__(
        self,
        divergence_tolerance_ms: int = 100,
        status_ports: Optional[Dict[int, str]] = None,
        channel_ports: Optional[Dict[int, str]] = None,
        fault_ports: Optional[Dict[int, str]] = None,
    ):
        """
        :param status_ports/channel_ports/fault_ports: Phase 4 允许上层根据
            bundle 动态传入这三组端口的 {port: fcc_name} 映射。未传则回落到
            模块级默认（9001/9011/9021 三组）。
        """
        self._divergence_tolerance_sec = max(0, divergence_tolerance_ms) / 1000.0
        self._status_ports = dict(status_ports) if status_ports else dict(STATUS_PORTS)
        self._channel_ports = dict(channel_ports) if channel_ports else dict(CHANNEL_PORTS)
        self._fault_ports = dict(fault_ports) if fault_ports else dict(FAULT_PORTS)

    # ---- public interface (same contract as Checksheet) ----

    def get_required_ports(self) -> List[int]:
        return sorted(
            set(self._status_ports) | set(self._channel_ports) | set(self._fault_ports)
        )

    def analyze(
        self,
        parsed_data: Dict[int, pd.DataFrame],
    ) -> Tuple[List[FccCheckResult], List[FccTimelineEvent]]:
        """
        Main entry. *parsed_data* maps port -> DataFrame(timestamp, raw_data).
        Returns (check_results, timeline_events).
        """
        events = self._build_sorted_events(parsed_data)
        if not events:
            return self._empty_results()

        # ---- state machine ----
        self._timeline: List[FccTimelineEvent] = []

        # main FCC state per reporting FCC
        self._vote_by_fcc: Dict[str, int] = {}
        self._current_main: Optional[str] = None
        self._main_history: List[Tuple[float, Optional[str]]] = []

        # sensor selection per FCC
        self._irs_sel: Dict[str, int] = {}
        self._ra_sel: Dict[str, int] = {}
        self._irs_divergence_start: Optional[float] = None
        self._ra_divergence_start: Optional[float] = None
        # deferred divergence events (held until duration confirmed)
        self._irs_pending_div: Optional[dict] = None
        self._ra_pending_div: Optional[dict] = None

        # fault state per FCC: {fcc: {channel: bool}}
        self._irs_fault: Dict[str, Dict[int, bool]] = {
            f: {0: False, 1: False, 2: False} for f in ("FCC1", "FCC2", "FCC3")
        }
        self._ra_fault: Dict[str, Dict[int, bool]] = {
            f: {0: False, 1: False} for f in ("FCC1", "FCC2", "FCC3")
        }

        # tracking for check-5 (selection vs fault inconsistency)
        self._fault_not_switched: List[dict] = []
        self._recovery_not_reselected: List[dict] = []

        # basic event log for causal chain matching
        self._basic_events: List[dict] = []

        for ts, port, raw_hex in events:
            data = _decode_payload(raw_hex)
            if data is None:
                continue
            if port in self._status_ports:
                self._handle_status(ts, port, data, raw_hex)
            elif port in self._channel_ports:
                self._handle_channel(ts, port, data, raw_hex)
            elif port in self._fault_ports:
                self._handle_fault(ts, port, data, raw_hex)

        last_ts = events[-1][0] if events else 0.0
        self._finalize_open_divergences(last_ts)
        self._detect_jitter()
        self._detect_selection_fault_inconsistency()
        self._detect_causal_chains()

        results = self._build_check_results()
        return results, self._timeline

    # ---- internal: build sorted event stream ----

    def _build_sorted_events(
        self, parsed_data: Dict[int, pd.DataFrame]
    ) -> List[Tuple[float, int, str]]:
        rows: List[Tuple[float, int, str]] = []
        for port, df in parsed_data.items():
            if port not in (set(self._status_ports) | set(self._channel_ports) | set(self._fault_ports)):
                continue
            for _, r in df.iterrows():
                rows.append((float(r["timestamp"]), port, str(r["raw_data"])))
        rows.sort(key=lambda x: x[0])
        return rows

    # ---- handlers ----

    def _handle_status(self, ts: float, port: int, data: bytes, raw_hex: str):
        fcc = self._status_ports[port]
        vote = int(data[FCC_STATUS_VOTE_OFFSET])
        prev_vote = self._vote_by_fcc.get(fcc)
        if prev_vote is not None and prev_vote == vote:
            return
        self._vote_by_fcc[fcc] = vote

        mains = _mains_from_vote(vote)
        new_main: Optional[str] = mains[0] if len(mains) == 1 else None

        if len(mains) == 0:
            self._emit_timeline(
                ts, fcc, port, "state_change", "无主飞控",
                f"{fcc} 报告表决结果 0x{vote:02X}，无主飞控",
                raw_hex, seq=1,
            )
            self._basic_events.append({"ts": ts, "type": "no_main", "fcc": fcc})
        elif len(mains) > 1:
            self._emit_timeline(
                ts, fcc, port, "state_change", "双主/多主飞控",
                f"{fcc} 报告表决结果 0x{vote:02X}，多个主飞控: {', '.join(mains)}",
                raw_hex, seq=1,
            )
            self._basic_events.append({"ts": ts, "type": "multi_main", "fcc": fcc, "mains": mains})

        if new_main != self._current_main:
            old = self._current_main
            self._current_main = new_main
            self._main_history.append((ts, new_main))
            if old is not None and new_main is not None:
                self._emit_timeline(
                    ts, fcc, port, "state_change", "主飞控切换",
                    f"主飞控从 {old} 切换到 {new_main}（{fcc} 报告 0x{vote:02X}）",
                    raw_hex, seq=1,
                )
                self._basic_events.append({
                    "ts": ts, "type": "main_switch",
                    "from": old, "to": new_main, "fcc": fcc,
                })

    def _handle_channel(self, ts: float, port: int, data: bytes, raw_hex: str):
        fcc = self._channel_ports[port]
        irs_val = int(data[FCC_CHANNEL_IRS_SEL_OFFSET])
        ra_val = (
            int(data[FCC_CHANNEL_RA_SEL_OFFSET])
            if len(data) > FCC_CHANNEL_RA_SEL_OFFSET
            else None
        )

        prev_irs = self._irs_sel.get(fcc)
        irs_changed = prev_irs is not None and prev_irs != irs_val
        if irs_changed:
            old_name = IRS_NAME.get(prev_irs, str(prev_irs))
            new_name = IRS_NAME.get(irs_val, str(irs_val))
            self._emit_timeline(
                ts, fcc, port, "state_change", "IRS 选择变化",
                f"{fcc} IRS 选择从 {old_name} 变为 {new_name}",
                raw_hex, seq=2,
            )
            self._basic_events.append({
                "ts": ts, "type": "irs_sel_change", "fcc": fcc,
                "from": prev_irs, "to": irs_val,
            })
        self._irs_sel[fcc] = irs_val

        if ra_val is not None:
            prev_ra = self._ra_sel.get(fcc)
            ra_changed = prev_ra is not None and prev_ra != ra_val
            if ra_changed:
                old_name = RA_NAME.get(prev_ra, str(prev_ra))
                new_name = RA_NAME.get(ra_val, str(ra_val))
                self._emit_timeline(
                    ts, fcc, port, "state_change", "RA 选择变化",
                    f"{fcc} RA 选择从 {old_name} 变为 {new_name}",
                    raw_hex, seq=2,
                )
                self._basic_events.append({
                    "ts": ts, "type": "ra_sel_change", "fcc": fcc,
                    "from": prev_ra, "to": ra_val,
                })
            self._ra_sel[fcc] = ra_val

        self._check_divergence(ts, "irs")
        self._check_divergence(ts, "ra")

    def _handle_fault(self, ts: float, port: int, data: bytes, raw_hex: str):
        fcc = self._fault_ports[port]

        irs_byte = int(data[FCC_FAULT_IRS_BITMAP_OFFSET])
        ra_byte = (
            int(data[FCC_FAULT_RA_BITMAP_OFFSET])
            if len(data) > FCC_FAULT_RA_BITMAP_OFFSET
            else 0
        )

        for bit, ch_name in [(0, "IRS1"), (1, "IRS2"), (2, "IRS3")]:
            new_val = bool(irs_byte & (1 << bit))
            old_val = self._irs_fault[fcc][bit]
            if new_val != old_val:
                self._irs_fault[fcc][bit] = new_val
                if new_val:
                    self._emit_timeline(
                        ts, fcc, port, "state_change", f"{ch_name} 通道故障",
                        f"{fcc} 判断 {ch_name} 通道故障",
                        raw_hex, seq=4,
                    )
                    self._basic_events.append({
                        "ts": ts, "type": "irs_fault_start",
                        "fcc": fcc, "channel": bit, "name": ch_name,
                    })
                else:
                    self._emit_timeline(
                        ts, fcc, port, "state_change", f"{ch_name} 故障恢复",
                        f"{fcc} 判断 {ch_name} 通道故障恢复",
                        raw_hex, seq=4,
                    )
                    self._basic_events.append({
                        "ts": ts, "type": "irs_fault_recover",
                        "fcc": fcc, "channel": bit, "name": ch_name,
                    })

        for bit, ch_name in [(0, "RA1"), (1, "RA2")]:
            new_val = bool(ra_byte & (1 << bit))
            old_val = self._ra_fault[fcc][bit]
            if new_val != old_val:
                self._ra_fault[fcc][bit] = new_val
                if new_val:
                    self._emit_timeline(
                        ts, fcc, port, "state_change", f"{ch_name} 通道故障",
                        f"{fcc} 判断 {ch_name} 通道故障",
                        raw_hex, seq=4,
                    )
                    self._basic_events.append({
                        "ts": ts, "type": "ra_fault_start",
                        "fcc": fcc, "channel": bit, "name": ch_name,
                    })
                else:
                    self._emit_timeline(
                        ts, fcc, port, "state_change", f"{ch_name} 故障恢复",
                        f"{fcc} 判断 {ch_name} 通道故障恢复",
                        raw_hex, seq=4,
                    )
                    self._basic_events.append({
                        "ts": ts, "type": "ra_fault_recover",
                        "fcc": fcc, "channel": bit, "name": ch_name,
                    })

    # ---- divergence detection (with tolerance-based deferred emit) ----

    def _check_divergence(self, ts: float, kind: str):
        sel = self._irs_sel if kind == "irs" else self._ra_sel
        name_map = IRS_NAME if kind == "irs" else RA_NAME
        label = "IRS" if kind == "irs" else "RA"
        div_start_attr = "_irs_divergence_start" if kind == "irs" else "_ra_divergence_start"
        pending_attr = "_irs_pending_div" if kind == "irs" else "_ra_pending_div"
        seq = 2

        if len(sel) < 2:
            return

        vals = list(sel.values())
        unique = set(vals)

        if len(unique) == 1:
            prev_start = getattr(self, div_start_attr)
            if prev_start is not None:
                duration = ts - prev_start
                pending = getattr(self, pending_attr)

                if duration <= self._divergence_tolerance_sec:
                    # too short — discard as async jitter
                    pass
                else:
                    if pending:
                        self._emit_timeline(**pending)
                        self._basic_events.append({
                            "ts": pending["ts"], "type": f"{kind}_divergence_start",
                            "pattern": pending.get("_pattern", "分歧"),
                        })
                    self._emit_timeline(
                        ts, "ALL", 0, "state_change",
                        f"{label} 选择分歧结束",
                        f"三机 {label} 选择恢复一致（持续 {duration:.2f}s）",
                        seq=seq,
                    )
                    self._basic_events.append({
                        "ts": ts, "type": f"{kind}_divergence_end",
                        "duration": duration,
                    })

                setattr(self, div_start_attr, None)
                setattr(self, pending_attr, None)
            return

        prev_start = getattr(self, div_start_attr)
        if prev_start is None:
            setattr(self, div_start_attr, ts)

            fcc_sels = ", ".join(
                f"{f}={name_map.get(v, str(v))}" for f, v in sel.items()
            )
            if len(unique) == 2 and len(sel) == 3:
                pattern = "2:1 分歧"
            elif len(unique) >= 3:
                pattern = "1:1:1 分歧"
            else:
                pattern = "分歧"

            # hold the start event — only emit if duration exceeds tolerance
            setattr(self, pending_attr, {
                "ts": ts, "device": "ALL", "port": 0,
                "event_type": "state_change",
                "event_name": f"{label} 选择 {pattern}",
                "event_description": f"三机 {label} 选择出现 {pattern}: {fcc_sels}",
                "seq": seq,
                "_pattern": pattern,
            })

        # check-3: main FCC disagrees with others (also subject to tolerance)
        if self._current_main and self._current_main in sel:
            main_val = sel[self._current_main]
            others_disagree = [
                f for f, v in sel.items()
                if f != self._current_main and v != main_val
            ]
            if others_disagree:
                div_start = getattr(self, div_start_attr)
                if div_start is not None and (ts - div_start) > self._divergence_tolerance_sec:
                    main_name = name_map.get(main_val, str(main_val))
                    detail = ", ".join(
                        f"{f}={name_map.get(sel[f], str(sel[f]))}"
                        for f in others_disagree
                    )
                    self._emit_timeline(
                        ts, self._current_main, 0, "state_change",
                        f"主飞控 {label} 选择与其他不一致",
                        f"主飞控 {self._current_main} 选择 {main_name}，"
                        f"但 {detail}",
                        seq=3,
                    )

    def _finalize_open_divergences(self, last_ts: float):
        """Flush any divergence that is still open at the end of the data stream."""
        for kind in ("irs", "ra"):
            div_start_attr = f"_{kind}_divergence_start"
            pending_attr = f"_{kind}_pending_div"
            label = "IRS" if kind == "irs" else "RA"

            div_start = getattr(self, div_start_attr, None)
            if div_start is None:
                continue
            duration = last_ts - div_start
            if duration <= self._divergence_tolerance_sec:
                continue

            pending = getattr(self, pending_attr, None)
            if pending:
                self._emit_timeline(**pending)
                self._basic_events.append({
                    "ts": pending["ts"], "type": f"{kind}_divergence_start",
                    "pattern": pending.get("_pattern", "分歧"),
                })
            self._emit_timeline(
                last_ts, "ALL", 0, "state_change",
                f"{label} 选择分歧持续至数据结束",
                f"三机 {label} 选择分歧持续 {duration:.2f}s 至数据结束未恢复",
                seq=2,
            )
            self._basic_events.append({
                "ts": last_ts, "type": f"{kind}_divergence_end",
                "duration": duration,
            })

    # ---- jitter detection (post-pass) ----

    def _detect_jitter(self):
        if len(self._main_history) < JITTER_THRESHOLD:
            return
        for i in range(len(self._main_history) - JITTER_THRESHOLD + 1):
            window = self._main_history[i: i + JITTER_THRESHOLD]
            if window[-1][0] - window[0][0] <= JITTER_WINDOW_SEC:
                ts = window[0][0]
                self._emit_timeline(
                    ts, "ALL", 0, "state_change",
                    "主飞控频繁抖动",
                    f"{JITTER_WINDOW_SEC}s 内主飞控切换 {JITTER_THRESHOLD} 次以上",
                    seq=1,
                )
                self._basic_events.append({"ts": ts, "type": "main_jitter"})
                break

    # ---- check-5: selection vs fault inconsistency (post-pass) ----

    def _detect_selection_fault_inconsistency(self):
        fault_starts = [
            e for e in self._basic_events
            if e["type"] in ("irs_fault_start", "ra_fault_start")
        ]
        fault_recovers = [
            e for e in self._basic_events
            if e["type"] in ("irs_fault_recover", "ra_fault_recover")
        ]
        sel_changes = [
            e for e in self._basic_events
            if e["type"] in ("irs_sel_change", "ra_sel_change")
        ]

        for fe in fault_starts:
            fcc = fe["fcc"]
            ch = fe["channel"]
            is_irs = fe["type"] == "irs_fault_start"
            current_sel = self._irs_sel.get(fcc) if is_irs else self._ra_sel.get(fcc)

            if current_sel == ch:
                switched = False
                for sc in sel_changes:
                    if (sc["fcc"] == fcc and sc["ts"] > fe["ts"]
                            and sc["ts"] - fe["ts"] <= FAULT_SWITCH_TIMEOUT_SEC):
                        if sc.get("from") == ch:
                            switched = True
                            break
                if not switched:
                    self._emit_timeline(
                        fe["ts"], fcc, 0, "state_change",
                        "故障后未及时切换",
                        f"{fcc} 在 {fe['name']} 故障后 {FAULT_SWITCH_TIMEOUT_SEC}s 内"
                        f"未切换选择",
                        seq=5,
                    )

        for re_evt in fault_recovers:
            fcc = re_evt["fcc"]
            ch = re_evt["channel"]
            is_irs = re_evt["type"] == "irs_fault_recover"
            current_sel = self._irs_sel.get(fcc) if is_irs else self._ra_sel.get(fcc)

            if current_sel != ch:
                reselected = False
                for sc in sel_changes:
                    if (sc["fcc"] == fcc and sc["ts"] > re_evt["ts"]
                            and sc["ts"] - re_evt["ts"] <= RECOVERY_RESELECT_TIMEOUT_SEC):
                        if sc.get("to") == ch:
                            reselected = True
                            break
                if not reselected:
                    self._emit_timeline(
                        re_evt["ts"], fcc, 0, "state_change",
                        "恢复后长期未重新纳入",
                        f"{fcc} 在 {re_evt['name']} 恢复后 {RECOVERY_RESELECT_TIMEOUT_SEC}s 内"
                        f"未重新选择该通道",
                        seq=5,
                    )

    # ---- check-6: causal chain events (post-pass) ----

    def _detect_causal_chains(self):
        for e in self._basic_events:
            if e["type"] in ("irs_fault_start", "ra_fault_start"):
                for e2 in self._basic_events:
                    if (e2["type"] == "main_switch"
                            and 0 < e2["ts"] - e["ts"] <= CAUSAL_WINDOW_SEC):
                        self._emit_timeline(
                            e["ts"], e["fcc"], 0, "causal_chain",
                            "通道故障 → 主飞控切换",
                            f"{e['name']} 故障后 {e2['ts'] - e['ts']:.2f}s，"
                            f"主飞控从 {e2['from']} 切换到 {e2['to']}",
                            seq=6,
                        )
                        break

            if e["type"] == "main_switch":
                for e2 in self._basic_events:
                    if (e2["type"] in ("irs_sel_change", "ra_sel_change")
                            and 0 < e2["ts"] - e["ts"] <= CAUSAL_WINDOW_SEC):
                        kind = "IRS" if "irs" in e2["type"] else "RA"
                        name_map = IRS_NAME if kind == "IRS" else RA_NAME
                        self._emit_timeline(
                            e["ts"], e2["fcc"], 0, "causal_chain",
                            f"主飞控切换 → {kind} 选择变化",
                            f"主飞控切换后 {e2['ts'] - e['ts']:.2f}s，"
                            f"{e2['fcc']} {kind} 从 "
                            f"{name_map.get(e2.get('from'), '?')} 变为 "
                            f"{name_map.get(e2.get('to'), '?')}",
                            seq=6,
                        )
                        break

        div_starts = [e for e in self._basic_events if e["type"].endswith("_divergence_start")]
        div_ends = [e for e in self._basic_events if e["type"].endswith("_divergence_end")]
        for ds in div_starts:
            kind = ds["type"].split("_")[0]
            for de in div_ends:
                if de["type"].startswith(kind) and de["ts"] > ds["ts"]:
                    label = "IRS" if kind == "irs" else "RA"
                    self._emit_timeline(
                        ds["ts"], "ALL", 0, "causal_chain",
                        f"{label} 分歧出现 → 分歧消失",
                        f"{label} {ds.get('pattern', '分歧')} 持续 {de.get('duration', 0):.2f}s 后恢复一致",
                        seq=6,
                    )
                    break

    # ---- emit helpers ----

    def _emit_timeline(
        self, ts, device, port, event_type, event_name, event_description,
        raw_hex=None, seq=None, **_extra,
    ):
        self._timeline.append(FccTimelineEvent(
            timestamp=ts,
            time_str=_ts_to_str(ts),
            device=device,
            port=port,
            event_type=event_type,
            event_name=event_name,
            event_description=event_description,
            raw_data_hex=raw_hex,
            related_check_sequence=seq,
        ))

    # ---- build final check results ----

    CHECK_DEFS = [
        _FccCheckItem(1, "主飞控异常", "主备表决", "检测无主、双主/多主、主飞控切换、频繁抖动"),
        _FccCheckItem(2, "三机传感器选择分歧", "传感器选择", "检测 IRS/RA 选择的 2:1、1:1:1 分歧及持续时长"),
        _FccCheckItem(3, "主飞控与其他飞控不一致", "传感器选择", "主飞控的 IRS/RA 选择与其他飞控不同"),
        _FccCheckItem(4, "飞控判断的通道故障", "通道故障", "IRS/RA 通道故障开始与恢复"),
        _FccCheckItem(5, "选择与故障状态不一致", "选择-故障一致性", "故障后未及时切换、恢复后未重新纳入"),
        _FccCheckItem(6, "因果链事件", "增强分析", "故障→切换、切换→选择变化、分歧出现→消失"),
    ]

    def _build_check_results(self) -> List[FccCheckResult]:
        results: List[FccCheckResult] = []
        for ci in self.CHECK_DEFS:
            related = [
                t for t in self._timeline
                if t.related_check_sequence == ci.sequence
            ]
            if not related:
                cr = FccCheckResult(
                    check_item=ci,
                    event_description="未发生",
                    content_result="not_detected",
                    overall_result="not_detected",
                )
            else:
                first = related[0]
                descriptions = "; ".join(t.event_description for t in related[:10])
                if len(related) > 10:
                    descriptions += f" …（共 {len(related)} 条）"
                cr = FccCheckResult(
                    check_item=ci,
                    event_time=first.time_str,
                    event_description=descriptions,
                    content_expected="",
                    content_actual=f"检测到 {len(related)} 条事件",
                    content_analysis=descriptions,
                    content_result="detected",
                    overall_result="detected",
                    evidence_data={
                        "event_count": len(related),
                        "first_event_ts": first.timestamp,
                    },
                )
            results.append(cr)
        return results

    def _empty_results(self):
        results = []
        for ci in self.CHECK_DEFS:
            results.append(FccCheckResult(
                check_item=ci,
                event_description="无数据",
                content_result="na",
                overall_result="na",
            ))
        return results, []
