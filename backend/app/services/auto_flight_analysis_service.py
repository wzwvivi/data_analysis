# -*- coding: utf-8 -*-
"""
自动飞行性能分析服务
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import DATA_DIR, UPLOAD_DIR
from ..models import (
    AutoFlightAnalysisTask,
    TouchdownAnalysisResult,
    SteadyStateAnalysisResult,
    ParseResult,
)
from .bundle import BundleNotFoundError, load_bundle
from .bundle import generator as bundle_generator
from .event_rules import AutoFlightAnalyzer
from .payload_layouts import (
    TSN_HEADER_LEN,
    AUTO_FLIGHT_FRAME_SIZE,
    AUTO_FLIGHT_LAYOUT,
)
from .pcap_reader import pcap_to_port_dataframes, iter_udp_packets
from .parsers.irs_parser import IRSParser


# ── 硬编码兜底（仅当 bundle 里没有 port_role=auto_flight 的声明时使用） ──
# 端口→设备名映射：来自《飞控发出数据-TSN版-V13.4》设备协议，而非 ICD
# —— ICD 里只写"这个端口属于飞控"，但具体哪台 FCC 是设备协议知识。
DEFAULT_AUTO_FLIGHT_PORTS = {9031: "FCC1", 9032: "FCC2", 9033: "FCC3"}
IRS_PORT_HINTS = {7004: "IRS1", 7005: "IRS2", 7006: "IRS3"}


def _decode_auto_flight_raw(raw_hex: str, port: int, fcc_label: Optional[str] = None) -> Optional[dict]:
    """从 raw_hex 解出自动飞行性能分析需要的字段。

    仅抽取"触底 / 稳态"分析链路上用到的 14 个字段，其余保持懒解析。
    """
    try:
        b = bytes.fromhex(raw_hex or "")
    except Exception:
        return None
    if len(b) < TSN_HEADER_LEN + AUTO_FLIGHT_FRAME_SIZE:
        return None
    d = b[TSN_HEADER_LEN:TSN_HEADER_LEN + AUTO_FLIGHT_FRAME_SIZE]
    # 懒解码：只取分析器真正用到的字段
    wanted = (
        "ap_engaged", "at_engaged", "air_ground", "flight_phase",
        "auto_mode", "lat_mode_active", "lon_mode_active",
        "thr_mode_active", "af_warning",
        "lat_track_error_m", "vert_track_error_m", "speed_cmd_mps",
        "current_altitude_m", "current_airspeed_mps", "current_groundspeed_mps",
    )
    import struct
    out: Dict[str, object] = {
        "source_port": port,
        "source_fcc": fcc_label or DEFAULT_AUTO_FLIGHT_PORTS.get(port),
    }
    try:
        for name in wanted:
            spec = AUTO_FLIGHT_LAYOUT.get(name)
            if not spec:
                continue
            off, typ = spec
            if typ == "u8":
                if off < len(d):
                    out[name] = int(d[off])
            elif typ == "f32":
                if off + 4 <= len(d):
                    out[name] = float(struct.unpack_from("<f", d, off)[0])
    except Exception:
        return None
    return out


class BundleResolutionError(RuntimeError):
    """用户显式选了 bundle 版本但加载/生成失败；strict 模式下需要硬失败。"""


async def _safe_load_bundle(
    db: AsyncSession,
    version_id: int,
    *,
    strict: bool = False,
):
    """加载 bundle，缺失时尝试生成一次；仍拿不到返回 None。

    :param strict: True 时任何失败都抛 :class:`BundleResolutionError`，
        用于"用户显式选了版本"的场景，避免结果与所选版本不匹配。
        False 时失败返回 None，保留尽力而为兜底。
    """
    try:
        return load_bundle(version_id)
    except BundleNotFoundError:
        try:
            await bundle_generator.generate_bundle(db, version_id)
            return load_bundle(version_id)
        except Exception as exc:
            if strict:
                raise BundleResolutionError(f"Bundle v{version_id} 无法生成: {exc}") from exc
            return None
    except Exception as exc:
        if strict:
            raise BundleResolutionError(f"Bundle v{version_id} 加载失败: {exc}") from exc
        return None


class AutoFlightAnalysisService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_port_mapping(
        self,
        bundle_version_id: Optional[int],
    ) -> Tuple[Dict[int, str], Dict[int, str]]:
        """返回 (auto_flight_port_map, irs_port_map)。

        - auto_flight_port_map: {port_number: fcc_label}，按 port_role='auto_flight'；
        - irs_port_map: {port_number: irs_label}，按 port_role='irs_input'。

        严格语义：
          * 用户已选 `bundle_version_id` → strict=True，bundle 加载失败直接抛
            `BundleResolutionError`（上游转任务失败，避免用户选了 vN 却没跑 vN）；
          * 未选版本 / bundle 软失败 → 回落硬编码默认。
        """
        if bundle_version_id is None:
            return dict(DEFAULT_AUTO_FLIGHT_PORTS), dict(IRS_PORT_HINTS)

        bundle = await _safe_load_bundle(
            self.db, int(bundle_version_id), strict=True
        )
        if bundle is None:
            # strict=True 下拿不到 bundle 会抛错，不会走到这里；作为防御性分支
            return dict(DEFAULT_AUTO_FLIGHT_PORTS), dict(IRS_PORT_HINTS)

        def _fcc_label(p: int) -> str:
            bp = bundle.ports.get(p)
            if bp:
                label = (bp.target_device or "").strip()
                if label:
                    return label
                mn = (bp.message_name or "").upper()
                for cand in ("FCC1", "FCC2", "FCC3", "BCM"):
                    if cand in mn:
                        return cand
            return DEFAULT_AUTO_FLIGHT_PORTS.get(p) or f"PORT_{p}"

        def _irs_label(p: int, fallback_idx: int) -> str:
            bp = bundle.ports.get(p)
            if bp:
                label = (bp.source_device or "").strip()
                if label:
                    return label
                mn = (bp.message_name or "").upper()
                for cand in ("IRS1", "IRS2", "IRS3"):
                    if cand in mn:
                        return cand
            return IRS_PORT_HINTS.get(p) or f"IRS{fallback_idx + 1}"

        auto_ports = bundle.ports_for_role("auto_flight")
        if auto_ports:
            auto_map = {p: _fcc_label(p) for p in auto_ports}
        else:
            # bundle 里未声明 auto_flight 角色 → 回落默认（不是硬错，允许老版本 bundle）
            auto_map = dict(DEFAULT_AUTO_FLIGHT_PORTS)

        irs_ports = bundle.ports_for_role("irs_input")
        if irs_ports:
            irs_map = {p: _irs_label(p, i) for i, p in enumerate(sorted(irs_ports))}
        else:
            irs_map = dict(IRS_PORT_HINTS)

        return auto_map, irs_map

    async def create_task_from_pcap(
        self,
        filename: str,
        file_path: str,
        source_type: str = "standalone",
        bundle_version_id: Optional[int] = None,
    ) -> AutoFlightAnalysisTask:
        task = AutoFlightAnalysisTask(
            parse_task_id=None,
            pcap_filename=filename,
            pcap_file_path=file_path,
            name=f"{filename} 自动飞行性能分析",
            source_type=source_type,
            status="pending",
            progress=0,
            bundle_version_id=(int(bundle_version_id) if bundle_version_id is not None else None),
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def create_task_from_parse(
        self,
        parse_task_id: int,
        bundle_version_id: Optional[int] = None,
    ) -> AutoFlightAnalysisTask:
        """基于已有解析任务创建分析任务。

        若未显式传入 `bundle_version_id`，默认继承自 `ParseTask.protocol_version_id`
        ——保证"基于 v5 解析结果跑的分析"显示的也是 v5。
        """
        resolved_bvid: Optional[int] = (
            int(bundle_version_id) if bundle_version_id is not None else None
        )
        if resolved_bvid is None:
            from ..models import ParseTask  # 延迟导入避免循环
            parse_row = (
                await self.db.execute(
                    select(ParseTask).where(ParseTask.id == parse_task_id)
                )
            ).scalar_one_or_none()
            if parse_row is not None:
                resolved_bvid = getattr(parse_row, "protocol_version_id", None)

        task = AutoFlightAnalysisTask(
            parse_task_id=parse_task_id,
            pcap_filename=None,
            pcap_file_path=None,
            name=f"解析任务#{parse_task_id} 自动飞行性能分析",
            source_type="parse_task",
            status="pending",
            progress=0,
            bundle_version_id=resolved_bvid,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def list_tasks(self, page: int = 1, page_size: int = 20) -> Tuple[List[AutoFlightAnalysisTask], int]:
        filt = True
        total = (
            await self.db.execute(select(func.count()).select_from(AutoFlightAnalysisTask).where(filt))
        ).scalar() or 0
        offset = (page - 1) * page_size
        rows = (
            await self.db.execute(
                select(AutoFlightAnalysisTask)
                .where(filt)
                .order_by(AutoFlightAnalysisTask.created_at.desc(), AutoFlightAnalysisTask.id.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    async def get_task(self, task_id: int) -> Optional[AutoFlightAnalysisTask]:
        return (
            await self.db.execute(
                select(AutoFlightAnalysisTask).where(AutoFlightAnalysisTask.id == task_id)
            )
        ).scalar_one_or_none()

    async def get_touchdowns(self, task_id: int) -> List[TouchdownAnalysisResult]:
        return (
            await self.db.execute(
                select(TouchdownAnalysisResult)
                .where(TouchdownAnalysisResult.analysis_task_id == task_id)
                .order_by(TouchdownAnalysisResult.sequence)
            )
        ).scalars().all()

    async def get_steady_states(self, task_id: int) -> List[SteadyStateAnalysisResult]:
        return (
            await self.db.execute(
                select(SteadyStateAnalysisResult)
                .where(SteadyStateAnalysisResult.analysis_task_id == task_id)
                .order_by(SteadyStateAnalysisResult.sequence)
            )
        ).scalars().all()

    async def run_analysis(self, task_id: int) -> bool:
        task = await self.get_task(task_id)
        if not task:
            return False
        task.status = "processing"
        task.progress = 5
        await self.db.commit()

        # Phase 4 + fix1：按 bundle 同时解析 auto_flight / irs_input 两组端口
        try:
            auto_flight_ports, irs_port_map = await self._resolve_port_mapping(
                getattr(task, "bundle_version_id", None)
            )
        except BundleResolutionError as exc:
            task.status = "failed"
            task.error_message = f"TSN 网络协议版本加载失败：{exc}"
            await self.db.commit()
            print(f"[AutoFlightAnalysis] {task.error_message}")
            return False

        print(
            f"[AutoFlightAnalysis] bundle_version_id={task.bundle_version_id} "
            f"auto_flight_ports={sorted(auto_flight_ports)} "
            f"irs_ports={sorted(irs_port_map)}"
        )

        temp_pcap_path = Path(task.pcap_file_path) if task.pcap_file_path else None
        try:
            if task.parse_task_id:
                task.progress = 15
                await self.db.commit()
                auto_df, irs_by_name = await self._load_from_parse_task(
                    task.parse_task_id, auto_flight_ports, irs_port_map
                )
                task.progress = 65
                await self.db.commit()
            else:
                if not task.pcap_file_path:
                    raise RuntimeError("任务未配置 pcap 文件路径")
                task.progress = 15
                await self.db.commit()
                auto_df = self._load_auto_from_pcap(task.pcap_file_path, auto_flight_ports)

                task.progress = 40
                await self.db.commit()
                irs_by_name = self._collect_irs_from_pcap(task.pcap_file_path, irs_port_map)

                task.progress = 65
                await self.db.commit()

            task.progress = 80
            await self.db.commit()

            analyzer = AutoFlightAnalyzer()
            out = analyzer.analyze(auto_df, irs_by_name)

            task.progress = 90
            await self.db.commit()
            await self._persist_outputs(task, out)
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            task.status = "failed"
            task.error_message = str(e)
            await self.db.commit()
            return False
        finally:
            if temp_pcap_path is not None:
                try:
                    shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
                    if temp_pcap_path.resolve().is_relative_to(shared_dir):
                        print(f"[AutoFlightAnalysis] 跳过共享文件: {temp_pcap_path.name}")
                    elif temp_pcap_path.is_file():
                        temp_pcap_path.unlink()
                        print(f"[AutoFlightAnalysis] 已删除临时文件: {temp_pcap_path}")
                except Exception as cleanup_err:
                    print(f"[AutoFlightAnalysis] 清理临时文件失败: {cleanup_err}")

    def _load_auto_from_pcap(
        self,
        pcap_path: str,
        port_label_map: Dict[int, str],
    ) -> pd.DataFrame:
        """从 pcap 抽取 port_label_map 指定端口的数据并解码。"""
        required = set(port_label_map.keys())
        if not required:
            return pd.DataFrame(columns=["timestamp"])
        port_map = pcap_to_port_dataframes(pcap_path, required)

        auto_rows: List[dict] = []
        for p, label in port_label_map.items():
            df = port_map.get(p)
            if df is None or df.empty:
                continue
            for row in df.itertuples(index=False):
                d = _decode_auto_flight_raw(getattr(row, "raw_data", ""), p, label)
                if d is None:
                    continue
                d["timestamp"] = float(getattr(row, "timestamp"))
                auto_rows.append(d)
        if not auto_rows:
            return pd.DataFrame(columns=["timestamp"])
        return pd.DataFrame(auto_rows).sort_values("timestamp").reset_index(drop=True)

    def _collect_irs_from_pcap(
        self,
        pcap_path: str,
        irs_port_map: Optional[Dict[int, str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        parser = IRSParser()
        seen_ports: set[int] = set()
        dev_rows: Dict[str, List[dict]] = {"IRS1": [], "IRS2": [], "IRS3": []}

        # IRSParser.device_id 约定:
        # 0 -> 惯导3, 1 -> 惯导1, 2 -> 惯导2
        device_to_name = {0: "IRS3", 1: "IRS1", 2: "IRS2"}
        allowed_ports = set(irs_port_map.keys()) if irs_port_map else None

        def _append_records(records: List[dict], port: int) -> None:
            for rec in records:
                dev_id = rec.get("device_id")
                irs_name = device_to_name.get(dev_id)
                if not irs_name:
                    continue
                dev_rows[irs_name].append({
                    "timestamp": rec.get("timestamp"),
                    "vertical_velocity": rec.get("vertical_velocity"),
                    "accel_z": rec.get("accel_z"),
                    "source_port": port,
                    "device_id": dev_id,
                })

        for ts, dport, payload in iter_udp_packets(pcap_path):
            if allowed_ports is not None and dport not in allowed_ports:
                continue
            seen_ports.add(dport)
            try:
                records = parser.feed_packet(payload, dport, ts)
            except Exception:
                records = []
            if records:
                _append_records(records, dport)

        # 结束后刷新缓冲区，尽量提取尾部残留完整帧
        for p in seen_ports:
            try:
                flushed = parser.flush_buffer(p)
            except Exception:
                flushed = []
            if flushed:
                _append_records(flushed, p)

        out: Dict[str, pd.DataFrame] = {}
        for name in ("IRS1", "IRS2", "IRS3"):
            rows = dev_rows[name]
            if not rows:
                out[name] = pd.DataFrame(columns=["timestamp", "vertical_velocity", "accel_z", "source_port", "device_id"])
                continue
            df = pd.DataFrame(rows)
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            out[name] = df
        return out

    async def _load_from_parse_task(
        self,
        parse_task_id: int,
        port_label_map: Dict[int, str],
        irs_port_map: Optional[Dict[int, str]] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        # 读取 parse_results，找到自动飞行与 IRS 相关端口 parquet
        parse_results = (
            await self.db.execute(
                select(ParseResult).where(ParseResult.task_id == parse_task_id)
            )
        ).scalars().all()

        auto_frames: List[pd.DataFrame] = []
        irs_by_name: Dict[str, pd.DataFrame] = {"IRS1": pd.DataFrame(), "IRS2": pd.DataFrame(), "IRS3": pd.DataFrame()}

        for r in parse_results:
            if not r.result_file:
                continue
            f = Path(r.result_file)
            if not f.is_file():
                # 兼容老数据：尝试按标准路径寻找
                fallback = DATA_DIR / "results" / str(parse_task_id) / f"port_{r.port_number}.parquet"
                if fallback.is_file():
                    f = fallback
                else:
                    continue
            try:
                df = pd.read_parquet(f)
            except Exception:
                continue

            if r.port_number in port_label_map:
                need = [c for c in [
                    "timestamp", "ap_engaged", "at_engaged", "air_ground",
                    "lon_mode_active", "af_warning",
                    "lat_track_error_m", "vert_track_error_m",
                    "speed_cmd_mps", "current_airspeed_mps",
                ] if c in df.columns]
                if need:
                    tdf = df[need].copy()
                    tdf["source_port"] = r.port_number
                    auto_frames.append(tdf)
            # IRS 端口：优先 bundle 解析出的 irs_port_map，缺省回落硬编码 IRS_PORT_HINTS
            effective_irs = irs_port_map if irs_port_map else IRS_PORT_HINTS
            if r.port_number in effective_irs:
                need = [c for c in ["timestamp", "vertical_velocity", "accel_z"] if c in df.columns]
                if need:
                    label = effective_irs[r.port_number]
                    if label in irs_by_name:
                        irs_by_name[label] = df[need].copy()

        auto_df = pd.concat(auto_frames, ignore_index=True) if auto_frames else pd.DataFrame(columns=["timestamp"])
        if not auto_df.empty and "timestamp" in auto_df.columns:
            auto_df = auto_df.sort_values("timestamp").reset_index(drop=True)
        return auto_df, irs_by_name

    async def _clear_old_results(self, task_id: int) -> None:
        await self.db.execute(
            TouchdownAnalysisResult.__table__.delete().where(
                TouchdownAnalysisResult.analysis_task_id == task_id
            )
        )
        await self.db.execute(
            SteadyStateAnalysisResult.__table__.delete().where(
                SteadyStateAnalysisResult.analysis_task_id == task_id
            )
        )
        await self.db.commit()

    async def _persist_outputs(self, task: AutoFlightAnalysisTask, out: Dict[str, any]) -> None:
        await self._clear_old_results(task.id)

        for d in out.get("touchdowns", []):
            row = TouchdownAnalysisResult(
                analysis_task_id=task.id,
                sequence=d.get("sequence", 0),
                touchdown_ts=d.get("touchdown_ts"),
                touchdown_time=d.get("touchdown_time"),
                irs1_vz=d.get("irs1_vz"),
                irs2_vz=d.get("irs2_vz"),
                irs3_vz=d.get("irs3_vz"),
                vz_spread=d.get("vz_spread"),
                irs1_az_peak=d.get("irs1_az_peak"),
                irs2_az_peak=d.get("irs2_az_peak"),
                irs3_az_peak=d.get("irs3_az_peak"),
                az_peak_spread=d.get("az_peak_spread"),
                rating=d.get("rating", "normal"),
                summary=d.get("summary"),
                chart_data=d.get("chart_data"),
            )
            self.db.add(row)

        for d in out.get("steady_states", []):
            row = SteadyStateAnalysisResult(
                analysis_task_id=task.id,
                sequence=d.get("sequence", 0),
                start_ts=d.get("start_ts"),
                end_ts=d.get("end_ts"),
                start_time=d.get("start_time"),
                end_time=d.get("end_time"),
                duration_s=d.get("duration_s", 0.0),
                mode_label=d.get("mode_label"),
                alt_bias=d.get("alt_bias"),
                alt_rms=d.get("alt_rms"),
                alt_max_abs=d.get("alt_max_abs"),
                lat_bias=d.get("lat_bias"),
                lat_rms=d.get("lat_rms"),
                lat_max_abs=d.get("lat_max_abs"),
                spd_bias=d.get("spd_bias"),
                spd_rms=d.get("spd_rms"),
                spd_max_abs=d.get("spd_max_abs"),
                rating=d.get("rating", "normal"),
                summary=d.get("summary"),
                chart_data=d.get("chart_data"),
            )
            self.db.add(row)

        task.touchdown_count = int(out.get("summary", {}).get("touchdown_count", 0))
        task.steady_count = int(out.get("summary", {}).get("steady_count", 0))
        task.status = "completed"
        task.progress = 100
        task.completed_at = datetime.utcnow()
        task.error_message = None
        await self.db.commit()
