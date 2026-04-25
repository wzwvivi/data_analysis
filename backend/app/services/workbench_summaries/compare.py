# -*- coding: utf-8 -*-
"""TSN 异常检查（双交换机比对）的领导级摘要 + 过程文字。

数据来源：

- ``CompareTask``：任务级汇总（首包时差、缺端口数、丢包总段数、时序通过数、综合结论）。
- ``ComparePortResult``：端口级覆盖与丢包段数；``in_switch1`` / ``in_switch2``
  指明缺哪一侧；``result`` 是端口级 pass/warning/fail。
- ``ComparePortTimingResult``：端口×交换机的周期/抖动；``jitter_pct``、
  ``compliance_rate_pct``、``result``。
- ``CompareGapRecord`` 聚合（service 已按端口/侧聚合后传入）：每端口每侧的
  丢包段数与预估缺失包数。

叙述策略：四步流程串叙述 + **点名最严重的端口**。哪些端口缺、哪些端口丢包最多、
哪些端口周期失败，都用具体端口号表达。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import empty_payload, join_sentences, status_tag


def _result_zh(value: Optional[str]) -> str:
    return {
        "pass": "通过",
        "warning": "警告",
        "fail": "失败",
    }.get((value or "").lower(), value or "—")


def _port_label(p: Any) -> str:
    """端口表达：``9013 (FCC1 状态)`` 这样既保留端口号又带可读 device 名。"""
    desc = (p.message_name or p.source_device or "").strip()
    if desc:
        return f"{p.port_number} ({desc})"
    return f"{p.port_number}"


# ──────────── 各步骤的句子 ────────────

def _step_sync(task: Any) -> Optional[str]:
    diff = getattr(task, "time_diff_ms", None)
    sync = getattr(task, "sync_result", None)
    if diff is None and not sync:
        return None
    if diff is None:
        return f"两交换机首包同步检查结果「{_result_zh(sync)}」"
    return (
        f"两交换机首包时间差 {float(diff):.1f} ms，同步检查结果「{_result_zh(sync)}」"
    )


def _step_coverage(task: Any, port_rows: List[Any]) -> Optional[str]:
    expected = int(getattr(task, "expected_port_count", 0) or 0)
    both = int(getattr(task, "both_present_count", 0) or 0)
    missing = int(getattr(task, "missing_count", 0) or 0)
    if expected == 0 and both == 0 and missing == 0:
        return None
    if missing == 0:
        return f"端口覆盖完整：{both}/{expected} 端口在两侧均有数据"
    # 找出"缺失最严重"的几条
    missing_ports = [
        p for p in port_rows
        if getattr(p, "in_switch1", True) is False or getattr(p, "in_switch2", True) is False
    ]
    if not missing_ports:
        return f"端口覆盖 {both}/{expected}，缺失 {missing} 个端口"
    only1 = [p for p in missing_ports if not p.in_switch2 and p.in_switch1]
    only2 = [p for p in missing_ports if not p.in_switch1 and p.in_switch2]
    none_side = [p for p in missing_ports if not p.in_switch1 and not p.in_switch2]

    parts: List[str] = []
    if only1:
        examples = "、".join(_port_label(p) for p in only1[:3])
        suffix = f"" if len(only1) <= 3 else f"…共 {len(only1)} 个"
        parts.append(f"仅交换机1有：{examples}{suffix}")
    if only2:
        examples = "、".join(_port_label(p) for p in only2[:3])
        suffix = f"" if len(only2) <= 3 else f"…共 {len(only2)} 个"
        parts.append(f"仅交换机2有：{examples}{suffix}")
    if none_side:
        examples = "、".join(_port_label(p) for p in none_side[:3])
        suffix = f"" if len(none_side) <= 3 else f"…共 {len(none_side)} 个"
        parts.append(f"两侧均缺：{examples}{suffix}")

    detail = "；".join(parts) if parts else f"缺失 {missing} 个"
    return f"端口覆盖 {both}/{expected}，{detail}"


def _step_continuity(task: Any, port_rows: List[Any], gap_aggs: List[Dict[str, Any]]) -> Optional[str]:
    periodic = int(getattr(task, "periodic_port_count", 0) or 0)
    gaps_ports = int(getattr(task, "ports_with_gaps", 0) or 0)
    total_gaps = int(getattr(task, "total_gap_count", 0) or 0)
    if periodic == 0 and gaps_ports == 0:
        return None
    if gaps_ports == 0:
        return f"周期端口（共 {periodic} 个）数据连续性良好，未检测到丢包段"

    # 把 ComparePortResult 的端口元信息放进字典
    port_meta: Dict[int, Any] = {p.port_number: p for p in port_rows}
    # 按端口聚合两侧丢包段数（gap_aggs 已是 (port, switch_index, gap_count, missing_pkts)）
    by_port: Dict[int, Dict[str, int]] = {}
    for a in gap_aggs:
        slot = by_port.setdefault(a["port_number"], {"gaps": 0, "missing": 0})
        slot["gaps"] += int(a.get("gap_count", 0) or 0)
        slot["missing"] += int(a.get("missing_pkts", 0) or 0)
    # 取丢包段最多的前 2 个端口
    ranked = sorted(by_port.items(), key=lambda kv: kv[1]["gaps"], reverse=True)[:2]
    samples = []
    for port_no, slot in ranked:
        meta = port_meta.get(port_no)
        label = _port_label(meta) if meta is not None else str(port_no)
        suffix = f"，预估缺失 {slot['missing']} 包" if slot["missing"] else ""
        samples.append(f"端口 {label} 丢包 {slot['gaps']} 段{suffix}")
    samples_str = "；".join(samples)
    out = f"周期端口共 {periodic} 个，{gaps_ports} 个存在丢包（共 {total_gaps} 段）"
    if samples_str:
        out += f"，最严重：{samples_str}"
    return out


def _step_timing(task: Any, timing_rows: List[Any]) -> Optional[str]:
    checked = int(getattr(task, "timing_checked_port_count", 0) or 0)
    fail = int(getattr(task, "timing_fail_count", 0) or 0)
    warn = int(getattr(task, "timing_warning_count", 0) or 0)
    pass_n = int(getattr(task, "timing_pass_count", 0) or 0)
    if checked == 0 and fail == 0 and warn == 0:
        return None
    if fail == 0 and warn == 0:
        return f"周期一致性检查 {checked} 个端口全部通过"
    bad_rows = [t for t in timing_rows if (t.result or "").lower() in ("warning", "fail")]
    bad_rows.sort(
        key=lambda t: (
            0 if (t.result or "").lower() == "fail" else 1,
            -(t.jitter_pct or 0),
        )
    )
    samples: List[str] = []
    for t in bad_rows[:2]:
        jitter_part = (
            f"抖动 {t.jitter_pct:.1f}%" if isinstance(t.jitter_pct, (int, float)) else "抖动 —"
        )
        samples.append(
            f"端口 {t.port_number} 交换机{t.switch_index}（{_result_zh(t.result)}，{jitter_part}）"
        )
    out = (
        f"周期一致性检查 {checked} 个端口：通过 {pass_n}、警告 {warn}、失败 {fail}"
    )
    if samples:
        out += "；最严重：" + "；".join(samples)
    return out


def _conclusion_sentence(task: Any) -> str:
    overall = (getattr(task, "overall_result", None) or "").lower()
    label = _result_zh(overall)
    fail = int(getattr(task, "timing_fail_count", 0) or 0)
    miss = int(getattr(task, "missing_count", 0) or 0)
    gaps_ports = int(getattr(task, "ports_with_gaps", 0) or 0)
    if overall == "pass":
        return f"综合结论「{label}」，TSN 网络数据传输质量良好"
    if overall in ("fail", "warning"):
        focus = []
        if miss:
            focus.append(f"{miss} 个端口缺失")
        if gaps_ports:
            focus.append(f"{gaps_ports} 个端口丢包")
        if fail:
            focus.append(f"{fail} 个端口周期失败")
        focus_str = "，".join(focus) if focus else "数据存在异常"
        return f"综合结论「{label}」，{focus_str}，建议工程师确认对应端口与时段"
    return "综合结论尚未生成"


# ──────────── 主入口 ────────────

def build_compare_narrative(
    task: Any,
    port_rows: Optional[List[Any]] = None,
    timing_rows: Optional[List[Any]] = None,
    gap_aggs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not task:
        return empty_payload()
    port_rows = port_rows or []
    timing_rows = timing_rows or []
    gap_aggs = gap_aggs or []

    overall = getattr(task, "overall_result", None)
    if (task.status or "").lower() == "failed":
        summary_text = f"TSN 异常检查失败：{task.error_message or '未知错误'}"
    elif overall:
        summary_text = (
            f"TSN 异常检查（双交换机比对）已完成，综合结论「{_result_zh(overall)}」。"
        )
    else:
        summary_text = "TSN 异常检查（双交换机比对）已完成。"

    sentences = [
        _step_sync(task),
        _step_coverage(task, port_rows),
        _step_continuity(task, port_rows, gap_aggs),
        _step_timing(task, timing_rows),
        _conclusion_sentence(task),
    ]
    timeline_narrative = join_sentences(sentences)

    tags: List[Dict[str, str]] = [status_tag(task.status)]
    if overall:
        color = (
            "success" if (overall or "").lower() == "pass"
            else "warning" if (overall or "").lower() == "warning"
            else "error"
        )
        tags.append({"label": f"综合 {_result_zh(overall)}", "color": color})

    miss = int(getattr(task, "missing_count", 0) or 0)
    gaps_ports = int(getattr(task, "ports_with_gaps", 0) or 0)
    fail = int(getattr(task, "timing_fail_count", 0) or 0)
    warn = int(getattr(task, "timing_warning_count", 0) or 0)
    if miss:
        tags.append({"label": f"缺失端口 {miss}", "color": "warning"})
    if gaps_ports:
        tags.append({"label": f"丢包端口 {gaps_ports}", "color": "warning"})
    if fail:
        tags.append({"label": f"周期失败 {fail}", "color": "error"})
    if warn:
        tags.append({"label": f"周期警告 {warn}", "color": "warning"})

    return {
        "summary_text": summary_text,
        "timeline_narrative": timeline_narrative,
        "summary_tags": tags,
    }
