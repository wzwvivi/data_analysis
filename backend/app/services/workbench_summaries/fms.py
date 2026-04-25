# -*- coding: utf-8 -*-
"""飞管事件分析的领导级摘要 + 时间线过程文字。

口径要点（与 ``checksheet.py`` / ``fms_event_analysis_service.py`` 对齐）：

- 检查行综合结论使用 **``pass`` / ``fail`` / ``warning`` / ``na``** 四值；
  task 上的 ``passed_checks`` / ``failed_checks`` 只统计 pass / fail，因此
  可能出现 ``passed + failed < total``——剩余的是 warning 或 na，**不是
  "待复核"**，叙述中要按"告警 / 无数据"分别说明。

- ``FmsEventCheckResult.category`` 通常是「启动检查 / 周期检查 / 响应检查」
  之类的大类，可以按 category 分组讲清楚哪一类有几条 fail / warning。

- 时间线 ``event_type`` 注释里枚举了 ``first_send`` / ``periodic`` /
  ``state_change`` / ``command`` / ``response``，但当前引擎主要写
  ``first_send`` / ``state_change`` / ``response``。叙述按存在的事件类型生成，
  避免硬编码出"周期阶段"这种实际未必有的事件。

输出仍是 ``summary_text`` / ``timeline_narrative`` / ``summary_tags`` 三件套。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from .base import empty_payload, fmt_time_str, join_sentences, status_tag


_MAX_NARRATIVE_SENTENCES = 7


def _device_label(device: Optional[str]) -> str:
    if not device:
        return "飞管"
    return str(device).strip() or "飞管"


# ──────────── 时间线分块叙述 ────────────

def _summarize_first_send(events: List[Any]) -> Optional[str]:
    firsts = [e for e in events if (e.event_type or "") == "first_send"]
    if not firsts:
        return None
    firsts = sorted(firsts, key=lambda e: e.timestamp or 0.0)
    head = firsts[0]
    head_time = fmt_time_str(head.time_str, head.timestamp)
    devices: List[str] = []
    for e in firsts[:4]:
        d = _device_label(e.device)
        if d not in devices:
            devices.append(d)
    devices_str = "、".join(devices) if devices else "飞管设备"
    if len(firsts) == 1:
        return (
            f"{head_time}，{devices_str} 在端口 {head.port or '—'} 首次发送"
            f"「{head.event_name or '相关报文'}」，链路进入启动发送阶段"
        )
    return (
        f"{head_time} 起，{devices_str} 先后首次发送相关报文，"
        f"链路进入启动发送阶段（共 {len(firsts)} 条 first_send）"
    )


def _summarize_periodic(events: List[Any]) -> Optional[str]:
    periods = [e for e in events if (e.event_type or "") == "periodic"]
    if not periods:
        return None
    periods = sorted(periods, key=lambda e: e.timestamp or 0.0)
    head = periods[0]
    return (
        f"{fmt_time_str(head.time_str, head.timestamp)} 起，"
        f"主要控制状态报文进入稳定周期发送阶段"
    )


def _summarize_state_changes(events: List[Any]) -> List[str]:
    changes = [e for e in events if (e.event_type or "") == "state_change"]
    if not changes:
        return []
    changes = sorted(changes, key=lambda e: e.timestamp or 0.0)
    out: List[str] = []
    for e in changes[:3]:
        t = fmt_time_str(e.time_str, e.timestamp)
        name = e.event_name or "状态变化"
        out.append(f"{t} 检测到「{name}」，系统状态发生变化")
    if len(changes) > 3:
        out.append(f"另有 {len(changes) - 3} 次状态变化未一一展开，可在明细时间线追溯")
    return out


def _summarize_command_response(events: List[Any]) -> List[str]:
    cmds = [e for e in events if (e.event_type or "") == "command"]
    resps = [e for e in events if (e.event_type or "") == "response"]
    if not cmds and not resps:
        return []
    out: List[str] = []
    used_resp_idx = set()
    cmds_sorted = sorted(cmds, key=lambda e: e.timestamp or 0.0)
    resps_sorted = sorted(resps, key=lambda e: e.timestamp or 0.0)
    paired = 0
    for c in cmds_sorted[:2]:
        ct = fmt_time_str(c.time_str, c.timestamp)
        cname = c.event_name or "指令"
        match = None
        for i, r in enumerate(resps_sorted):
            if i in used_resp_idx:
                continue
            if (r.timestamp or 0.0) >= (c.timestamp or 0.0):
                match = (i, r)
                break
        if match:
            i, r = match
            used_resp_idx.add(i)
            rt = fmt_time_str(r.time_str, r.timestamp)
            rname = r.event_name or "响应"
            out.append(f"{ct} 发出「{cname}」，{rt} 收到「{rname}」，指令交互形成闭环")
            paired += 1
        else:
            out.append(f"{ct} 发出「{cname}」，未在数据中找到对应响应")
    leftover_resp = len(resps_sorted) - len(used_resp_idx)
    if leftover_resp > 0 and not paired:
        r = resps_sorted[0]
        rt = fmt_time_str(r.time_str, r.timestamp)
        out.append(f"{rt} 收到「{r.event_name or '响应'}」，但未匹配到对应指令")
    return out


# ──────────── 检查单聚合 ────────────

def _aggregate_checks(check_results: List[Any]) -> Dict[str, Any]:
    total = len(check_results)
    pass_n = sum(1 for c in check_results if (c.overall_result or "") == "pass")
    fail_n = sum(1 for c in check_results if (c.overall_result or "") == "fail")
    warn_n = sum(1 for c in check_results if (c.overall_result or "") == "warning")
    na_n = sum(1 for c in check_results if (c.overall_result or "") == "na")

    by_category: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "fail": 0, "warning": 0})
    fail_examples: List[Any] = []
    for c in check_results:
        cat = (c.category or "其它").strip() or "其它"
        by_category[cat]["total"] += 1
        result = (c.overall_result or "").lower()
        if result == "fail":
            by_category[cat]["fail"] += 1
            fail_examples.append(c)
        elif result == "warning":
            by_category[cat]["warning"] += 1
    return {
        "total": total,
        "pass": pass_n,
        "fail": fail_n,
        "warning": warn_n,
        "na": na_n,
        "by_category": dict(by_category),
        "fail_examples": fail_examples,
    }


def _summary_text(task: Any, agg: Dict[str, Any]) -> str:
    if (task.status or "").lower() == "failed":
        return f"飞管事件分析失败：{task.error_message or '未知错误'}"
    total = agg["total"]
    if total == 0:
        return "飞管事件分析已完成，但本次未生成检查结果（请确认上传数据的端口覆盖）。"
    seg = [f"{agg['pass']} 项通过"]
    if agg["fail"]:
        seg.append(f"{agg['fail']} 项失败")
    if agg["warning"]:
        seg.append(f"{agg['warning']} 项告警")
    if agg["na"]:
        seg.append(f"{agg['na']} 项无数据")
    return f"飞管事件分析已完成，{total} 项检查里 " + "、".join(seg) + "。"


def _category_breakdown_sentence(agg: Dict[str, Any]) -> Optional[str]:
    """按 category 写一句"哪类有几条不通过"。"""
    parts: List[str] = []
    for cat, counts in agg["by_category"].items():
        if counts["fail"] == 0 and counts["warning"] == 0:
            continue
        if counts["fail"] and counts["warning"]:
            parts.append(f"{cat} 失败 {counts['fail']}、告警 {counts['warning']}")
        elif counts["fail"]:
            parts.append(f"{cat} 失败 {counts['fail']}")
        else:
            parts.append(f"{cat} 告警 {counts['warning']}")
    if not parts:
        return None
    return "检查单分类：" + "；".join(parts) + "，建议优先复核"


def _fail_examples_sentence(agg: Dict[str, Any]) -> Optional[str]:
    if not agg["fail_examples"]:
        return None
    examples = agg["fail_examples"][:2]
    parts: List[str] = []
    for c in examples:
        when = c.event_time or "时间未知"
        parts.append(f"「{c.check_name}」({when})")
    sentence = "未通过项示例：" + "、".join(parts)
    if len(agg["fail_examples"]) > len(examples):
        sentence += f"，共 {len(agg['fail_examples'])} 例"
    return sentence


def _conclusion_sentence(agg: Dict[str, Any]) -> str:
    total = agg["total"]
    if total == 0:
        return "本次飞管事件分析未识别出可执行的检查项"
    if agg["fail"] or agg["warning"]:
        return (
            "整体看，飞管链路过程可追溯，但存在未通过/告警项，"
            "建议在底部明细中复核对应时间段"
        )
    if agg["na"]:
        return (
            f"整体看，飞管链路已通过 {agg['pass']} 项检查，"
            f"另有 {agg['na']} 项因缺少数据未参与判断"
        )
    return f"整体看，飞管链路过程完整，{total} 项检查全部通过，未见严重通信中断"


def _build_tags(task: Any, agg: Dict[str, Any], timeline_count: int) -> List[Dict[str, str]]:
    tags: List[Dict[str, str]] = [status_tag(task.status)]
    if agg["total"]:
        tags.append({"label": f"检查 {agg['total']}", "color": "blue"})
        if agg["fail"]:
            tags.append({"label": f"失败 {agg['fail']}", "color": "error"})
        if agg["warning"]:
            tags.append({"label": f"告警 {agg['warning']}", "color": "warning"})
        if agg["na"]:
            tags.append({"label": f"无数据 {agg['na']}", "color": "default"})
        if not agg["fail"] and not agg["warning"] and not agg["na"]:
            tags.append({"label": "全部通过", "color": "success"})
    if timeline_count:
        tags.append({"label": f"时间线 {timeline_count}", "color": "geekblue"})
    return tags


# ──────────── 主入口 ────────────

def build_fms_narrative(
    task: Any,
    timeline_events: List[Any],
    check_results: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    if not task:
        return empty_payload()
    check_results = check_results or []
    timeline_events = timeline_events or []

    agg = _aggregate_checks(check_results)
    summary_text = _summary_text(task, agg)

    # 时间线段
    sentences: List[Optional[str]] = []
    sentences.append(_summarize_first_send(timeline_events))
    sentences.append(_summarize_periodic(timeline_events))
    for s in _summarize_state_changes(timeline_events):
        sentences.append(s)
    for s in _summarize_command_response(timeline_events):
        sentences.append(s)

    # 检查单结果分类（fail/warning 的话需要单独一句）
    cat_sentence = _category_breakdown_sentence(agg)
    fail_sentence = _fail_examples_sentence(agg)

    # 控总长：时间线最多前 4 句，再加分类与示例，再加结论
    sentences = [s for s in sentences if s][:4]
    if cat_sentence:
        sentences.append(cat_sentence)
    if fail_sentence:
        sentences.append(fail_sentence)
    sentences.append(_conclusion_sentence(agg))
    sentences = sentences[:_MAX_NARRATIVE_SENTENCES]
    timeline_narrative = join_sentences(sentences)

    tags = _build_tags(task, agg, len(timeline_events))

    return {
        "summary_text": summary_text,
        "timeline_narrative": timeline_narrative,
        "summary_tags": tags,
    }
