# -*- coding: utf-8 -*-
"""飞控事件分析的领导级摘要 + 过程文字。

口径要点（与 ``fcc_checksheet.py`` 对齐）：

- 飞控检查单是 6 项固定规则：
  1. 主飞控异常（无主 / 多主 / 主切换 / 频繁抖动）
  2. 三机传感器选择分歧（IRS/RA 2:1、1:1:1、持续时长、是否恢复）
  3. 主飞控与其他飞控选择不一致（主飞控站位）
  4. 飞控判断的通道故障（IRS/RA 故障与恢复，含通道编号）
  5. 选择与故障状态不一致（**故障后未及时切走 / 恢复后未重新选回**——强信号）
  6. 因果链事件（故障→主切换、切换→选择变化、分歧出现→消失）

- 检查行的综合结论使用 **``detected`` / ``not_detected`` / ``na``**，
  *不是* ``pass`` / ``fail``——所以摘要里只能讲"是否发生"，不能讲"通过/失败"。

- 错配（第 5 项）任意一例都应当点名提示，因为这是飞控控制律层面的潜在故障。

输出仍是 ``summary_text`` / ``timeline_narrative`` / ``summary_tags`` 三件套。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .base import empty_payload, fmt_time_str, join_sentences, status_tag


# 单个 builder 的句子上限：飞控比飞管语义更密，给 8 句额度
_MAX_NARRATIVE_SENTENCES = 8


# ──────────── 时间线分类（与 fcc_checksheet.py 中的 event_name 对齐） ────────────

def _categorize(events: List[Any]) -> Dict[str, List[Any]]:
    cats: Dict[str, List[Any]] = {
        # 主控相关
        "main_lost": [],          # 无主飞控
        "main_multi": [],         # 双主/多主
        "main_switch": [],        # 主飞控切换
        "main_jitter": [],        # 主飞控频繁抖动
        # 选择分歧
        "irs_div_2_1": [],
        "irs_div_111": [],
        "irs_div_other": [],
        "irs_div_end": [],
        "irs_div_open_end": [],   # 持续到数据结束
        "ra_div_2_1": [],
        "ra_div_111": [],
        "ra_div_other": [],
        "ra_div_end": [],
        "ra_div_open_end": [],
        # 主飞控站位
        "main_misalign_irs": [],
        "main_misalign_ra": [],
        # 通道故障
        "ch_fault": [],           # X 通道故障
        "ch_recover": [],         # X 故障恢复
        # 错配（强信号）
        "fault_no_switch": [],
        "recover_no_reselect": [],
        # 因果链
        "chain_fault_switch": [],
        "chain_switch_irs": [],
        "chain_switch_ra": [],
        "chain_irs_div_pair": [],
        "chain_ra_div_pair": [],
        # 普通选择变化（不是分歧）
        "irs_select": [],
        "ra_select": [],
        "other": [],
    }
    for e in events:
        name = (e.event_name or "").strip()
        etype = (e.event_type or "").strip()
        # 因果链优先（event_type == causal_chain）
        if etype == "causal_chain":
            if "故障" in name and "切换" in name:
                cats["chain_fault_switch"].append(e)
            elif "切换" in name and "IRS" in name:
                cats["chain_switch_irs"].append(e)
            elif "切换" in name and "RA" in name:
                cats["chain_switch_ra"].append(e)
            elif "IRS" in name and "分歧" in name:
                cats["chain_irs_div_pair"].append(e)
            elif "RA" in name and "分歧" in name:
                cats["chain_ra_div_pair"].append(e)
            else:
                cats["other"].append(e)
            continue
        # 主控
        if "无主飞控" in name:
            cats["main_lost"].append(e)
        elif "双主" in name or "多主" in name:
            cats["main_multi"].append(e)
        elif "主飞控频繁抖动" in name:
            cats["main_jitter"].append(e)
        elif "主飞控切换" in name:
            cats["main_switch"].append(e)
        # 主飞控站位
        elif "主飞控 IRS 选择与其他不一致" in name:
            cats["main_misalign_irs"].append(e)
        elif "主飞控 RA 选择与其他不一致" in name:
            cats["main_misalign_ra"].append(e)
        # IRS 分歧
        elif "IRS 选择 2:1 分歧" in name:
            cats["irs_div_2_1"].append(e)
        elif "IRS 选择 1:1:1 分歧" in name:
            cats["irs_div_111"].append(e)
        elif "IRS 选择 分歧" in name:
            cats["irs_div_other"].append(e)
        elif "IRS 选择分歧结束" in name:
            cats["irs_div_end"].append(e)
        elif "IRS 选择分歧持续至数据结束" in name:
            cats["irs_div_open_end"].append(e)
        # RA 分歧
        elif "RA 选择 2:1 分歧" in name:
            cats["ra_div_2_1"].append(e)
        elif "RA 选择 1:1:1 分歧" in name:
            cats["ra_div_111"].append(e)
        elif "RA 选择 分歧" in name:
            cats["ra_div_other"].append(e)
        elif "RA 选择分歧结束" in name:
            cats["ra_div_end"].append(e)
        elif "RA 选择分歧持续至数据结束" in name:
            cats["ra_div_open_end"].append(e)
        # 故障
        elif "故障恢复" in name:
            cats["ch_recover"].append(e)
        elif "通道故障" in name:
            cats["ch_fault"].append(e)
        # 错配
        elif "故障后未及时切换" in name:
            cats["fault_no_switch"].append(e)
        elif "恢复后长期未重新纳入" in name:
            cats["recover_no_reselect"].append(e)
        # 普通选择变化
        elif "IRS 选择变化" in name:
            cats["irs_select"].append(e)
        elif "RA 选择变化" in name:
            cats["ra_select"].append(e)
        else:
            cats["other"].append(e)
    return cats


# ──────────── 各业务块的句子生成 ────────────

def _block_main_state(cats: Dict[str, List[Any]]) -> Optional[str]:
    parts: List[str] = []
    if cats["main_lost"]:
        evs = sorted(cats["main_lost"], key=lambda e: e.timestamp or 0.0)
        parts.append(
            f"出现 {len(evs)} 次「无主飞控」（首次 {fmt_time_str(evs[0].time_str, evs[0].timestamp)}）"
        )
    if cats["main_multi"]:
        evs = sorted(cats["main_multi"], key=lambda e: e.timestamp or 0.0)
        parts.append(
            f"出现 {len(evs)} 次「双主/多主」（首次 {fmt_time_str(evs[0].time_str, evs[0].timestamp)}）"
        )
    if cats["main_switch"]:
        evs = sorted(cats["main_switch"], key=lambda e: e.timestamp or 0.0)
        parts.append(
            f"主飞控发生 {len(evs)} 次切换（首次 {fmt_time_str(evs[0].time_str, evs[0].timestamp)}）"
        )
    if cats["main_jitter"]:
        parts.append(f"识别到 {len(cats['main_jitter'])} 段主飞控频繁抖动")
    if not parts:
        return None
    return "主控状态：" + "；".join(parts)


def _pair_divergence(opens: List[Any], ends: List[Any], open_to_end: List[Any]) -> List[Tuple[Any, Optional[Any], Optional[float]]]:
    """配对「分歧出现」与「分歧结束」事件，返回 (open, end, duration_s)。

    没成对的（持续到数据结束）通过 ``open_to_end`` 单独计入。
    """
    opens_sorted = sorted(opens, key=lambda e: e.timestamp or 0.0)
    ends_sorted = sorted(ends, key=lambda e: e.timestamp or 0.0)
    used = set()
    result: List[Tuple[Any, Optional[Any], Optional[float]]] = []
    for o in opens_sorted:
        match: Optional[Any] = None
        for i, en in enumerate(ends_sorted):
            if i in used:
                continue
            if (en.timestamp or 0.0) >= (o.timestamp or 0.0):
                match = en
                used.add(i)
                break
        if match is not None:
            duration = (match.timestamp or 0.0) - (o.timestamp or 0.0)
            result.append((o, match, max(duration, 0.0)))
        else:
            result.append((o, None, None))
    # 显式标记的"持续至数据结束"独立成段，duration 留空表示未恢复
    for o in open_to_end:
        result.append((o, None, None))
    return result


def _fmt_duration_short(seconds: Optional[float]) -> str:
    if seconds is None:
        return "未恢复"
    s = float(seconds)
    if s < 60:
        return f"{int(round(s))}s"
    if s < 3600:
        return f"{s / 60:.1f}min"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    return f"{h}h{m}min"


def _block_divergence(cats: Dict[str, List[Any]], label: str) -> Optional[str]:
    """为 IRS 或 RA 生成一段分歧叙述。"""
    prefix = "irs" if label == "IRS" else "ra"
    opens = (
        cats[f"{prefix}_div_2_1"]
        + cats[f"{prefix}_div_111"]
        + cats[f"{prefix}_div_other"]
    )
    if not opens and not cats[f"{prefix}_div_open_end"]:
        return None
    pairs = _pair_divergence(opens, cats[f"{prefix}_div_end"], cats[f"{prefix}_div_open_end"])
    if not pairs:
        return None
    n = len(pairs)
    n_unrecovered = sum(1 for _, e, _ in pairs if e is None)
    # 统计模式分布
    modes_2_1 = sum(1 for o, _, _ in pairs if "2:1" in (o.event_name or ""))
    modes_111 = sum(1 for o, _, _ in pairs if "1:1:1" in (o.event_name or ""))
    # 取最长一段做亮点
    pairs_sorted = sorted(
        pairs,
        key=lambda p: (p[2] if p[2] is not None else float("inf")),
        reverse=True,
    )
    longest = pairs_sorted[0]
    longest_open_t = fmt_time_str(longest[0].time_str, longest[0].timestamp)
    longest_dur = _fmt_duration_short(longest[2])
    mode_parts = []
    if modes_2_1:
        mode_parts.append(f"2:1×{modes_2_1}")
    if modes_111:
        mode_parts.append(f"1:1:1×{modes_111}")
    mode_str = "（" + "、".join(mode_parts) + "）" if mode_parts else ""
    sentence = f"{label} 选择共 {n} 段分歧{mode_str}"
    if n == 1:
        sentence += f"，于 {longest_open_t} 起持续 {longest_dur}"
    else:
        sentence += f"，最长一段从 {longest_open_t} 起持续 {longest_dur}"
    if n_unrecovered:
        sentence += f"，其中 {n_unrecovered} 段截至数据结束未恢复"
    return sentence


def _block_main_misalignment(cats: Dict[str, List[Any]]) -> Optional[str]:
    n_irs = len(cats["main_misalign_irs"])
    n_ra = len(cats["main_misalign_ra"])
    if n_irs == 0 and n_ra == 0:
        return None
    parts = []
    if n_irs:
        parts.append(f"IRS 站位不一致 {n_irs} 次")
    if n_ra:
        parts.append(f"RA 站位不一致 {n_ra} 次")
    return "分歧期间，主飞控存在" + "、".join(parts) + "，需复核主控决策依据"


def _channel_prefix(event_name: str) -> str:
    """从 'IRS2 通道故障' 等事件名取通道前缀（IRS1/IRS2/IRS3/RA1/RA2）。"""
    return (event_name or "").split(" ")[0]


def _block_channel_faults(cats: Dict[str, List[Any]]) -> Optional[str]:
    faults = sorted(cats["ch_fault"], key=lambda e: e.timestamp or 0.0)
    recovers = sorted(cats["ch_recover"], key=lambda e: e.timestamp or 0.0)
    if not faults and not recovers:
        return None
    used = set()
    pairs: List[Tuple[Any, Optional[Any], Optional[float]]] = []
    for f in faults:
        match: Optional[Any] = None
        f_prefix = _channel_prefix(f.event_name or "")
        for i, r in enumerate(recovers):
            if i in used:
                continue
            if (r.timestamp or 0.0) < (f.timestamp or 0.0):
                continue
            if _channel_prefix(r.event_name or "") == f_prefix:
                match = r
                used.add(i)
                break
        if match is not None:
            duration = (match.timestamp or 0.0) - (f.timestamp or 0.0)
            pairs.append((f, match, max(duration, 0.0)))
        else:
            pairs.append((f, None, None))
    n_pair = len(pairs)
    n_unrecovered = sum(1 for _, m, _ in pairs if m is None)
    # 按通道聚合次数
    by_channel: Dict[str, int] = {}
    for f, _, _ in pairs:
        ch = _channel_prefix(f.event_name or "") or "未知"
        by_channel[ch] = by_channel.get(ch, 0) + 1
    by_channel_str = "、".join(f"{k}×{v}" for k, v in sorted(by_channel.items()))
    sentence = f"通道故障共 {n_pair} 次（{by_channel_str}）"
    # 最长故障段
    longest = max(
        ((f, m, d) for f, m, d in pairs if d is not None),
        key=lambda p: p[2],
        default=None,
    )
    if longest is not None:
        ft = fmt_time_str(longest[0].time_str, longest[0].timestamp)
        sentence += f"，最长一段为 {_channel_prefix(longest[0].event_name or '')} 自 {ft} 起持续 {_fmt_duration_short(longest[2])}"
    if n_unrecovered:
        sentence += f"，其中 {n_unrecovered} 次截至数据结束未恢复"
    return sentence


def _block_misconfig(cats: Dict[str, List[Any]]) -> Optional[str]:
    n_no_switch = len(cats["fault_no_switch"])
    n_no_reselect = len(cats["recover_no_reselect"])
    if n_no_switch == 0 and n_no_reselect == 0:
        return None
    parts = []
    if n_no_switch:
        evs = sorted(cats["fault_no_switch"], key=lambda e: e.timestamp or 0.0)
        t = fmt_time_str(evs[0].time_str, evs[0].timestamp)
        parts.append(f"故障后未及时切换 {n_no_switch} 例（首例 {t}）")
    if n_no_reselect:
        evs = sorted(cats["recover_no_reselect"], key=lambda e: e.timestamp or 0.0)
        t = fmt_time_str(evs[0].time_str, evs[0].timestamp)
        parts.append(f"恢复后长期未重新纳入 {n_no_reselect} 例（首例 {t}）")
    return "选择-故障错配（需重点复核）：" + "；".join(parts)


def _block_normal_selection(cats: Dict[str, List[Any]]) -> Optional[str]:
    """正常的 IRS / RA 选择切换（未触发分歧、未错配），单独点一句。

    业务上：每次 IRS/RA 选择变化都是飞控按规则切换通道——本身不一定异常，
    但如果数量很多就值得让人注意（可能是抖动信号源），所以即使没有分歧也单写一句。
    """
    irs_n = len(cats["irs_select"])
    ra_n = len(cats["ra_select"])
    if irs_n == 0 and ra_n == 0:
        return None
    parts = []
    if irs_n:
        parts.append(f"IRS 选择变化 {irs_n} 次")
    if ra_n:
        parts.append(f"RA 选择变化 {ra_n} 次")
    return "传感器选择：" + "、".join(parts) + "（未触发分歧）"


def _block_causal(cats: Dict[str, List[Any]]) -> Optional[str]:
    parts: List[str] = []
    if cats["chain_fault_switch"]:
        parts.append(f"通道故障 → 主切换 {len(cats['chain_fault_switch'])} 例")
    if cats["chain_switch_irs"]:
        parts.append(f"主切换 → IRS 选择变化 {len(cats['chain_switch_irs'])} 例")
    if cats["chain_switch_ra"]:
        parts.append(f"主切换 → RA 选择变化 {len(cats['chain_switch_ra'])} 例")
    if cats["chain_irs_div_pair"]:
        parts.append(f"IRS 分歧出现→消失 {len(cats['chain_irs_div_pair'])} 对")
    if cats["chain_ra_div_pair"]:
        parts.append(f"RA 分歧出现→消失 {len(cats['chain_ra_div_pair'])} 对")
    if not parts:
        return None
    return "因果链：识别到 " + "、".join(parts)


# ──────────── 检查单结果 → 计数 / 文案 ────────────

def _aggregate_checks(check_results: List[Any]) -> Dict[str, int]:
    detected = sum(1 for c in check_results if (c.overall_result or "") == "detected")
    not_detected = sum(1 for c in check_results if (c.overall_result or "") == "not_detected")
    na = sum(1 for c in check_results if (c.overall_result or "") == "na")
    return {
        "total": len(check_results),
        "detected": detected,
        "not_detected": not_detected,
        "na": na,
    }


def _summary_text(task: Any, agg: Dict[str, int], timeline_count: int) -> str:
    if (task.status or "").lower() == "failed":
        return f"飞控事件分析失败：{task.error_message or '未知错误'}"
    # 历史任务可能 check_results 表为空，但仍有时间线事件——以时间线为主成句
    if agg["total"] == 0:
        if timeline_count > 0:
            return (
                f"飞控事件分析已完成，本次共记录 {timeline_count} 条时间线事件"
                f"（旧版任务未保存检查单结果）。"
            )
        return "飞控事件分析已完成，但本次未生成检查结果（可能数据缺失或端口映射失败）。"
    seg = [f"{agg['detected']} 项检测到事件", f"{agg['not_detected']} 项未发生"]
    if agg["na"]:
        seg.append(f"{agg['na']} 项无数据")
    return f"飞控事件分析已完成，{agg['total']} 项检查里 " + "、".join(seg) + "。"


def _build_tags(
    task: Any,
    agg: Dict[str, int],
    cats: Dict[str, List[Any]],
    timeline_count: int,
) -> List[Dict[str, str]]:
    tags: List[Dict[str, str]] = [status_tag(task.status)]
    if agg["total"]:
        tags.append({"label": f"检查 {agg['total']}", "color": "blue"})
        if agg["detected"]:
            tags.append({"label": f"已发生 {agg['detected']}", "color": "warning"})
        if agg["not_detected"]:
            tags.append({"label": f"未发生 {agg['not_detected']}", "color": "success"})
        if agg["na"]:
            tags.append({"label": f"无数据 {agg['na']}", "color": "default"})
    elif timeline_count:
        tags.append({"label": f"时间线 {timeline_count}", "color": "geekblue"})

    # 关键风险信号点名（即使数量很小也单独成 tag，便于一眼看到）
    if cats["fault_no_switch"]:
        tags.append({"label": f"故障未切走 {len(cats['fault_no_switch'])}", "color": "error"})
    if cats["recover_no_reselect"]:
        tags.append({"label": f"恢复未重选 {len(cats['recover_no_reselect'])}", "color": "error"})
    if cats["main_lost"]:
        tags.append({"label": f"无主 {len(cats['main_lost'])}", "color": "error"})
    if cats["main_multi"]:
        tags.append({"label": f"多主 {len(cats['main_multi'])}", "color": "error"})
    if cats["main_switch"]:
        tags.append({"label": f"主切换 {len(cats['main_switch'])}", "color": "warning"})
    if cats["main_jitter"]:
        tags.append({"label": "主控抖动", "color": "error"})
    return tags


# ──────────── 主入口 ────────────

def build_fcc_narrative(
    task: Any,
    timeline_events: List[Any],
    check_results: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    if not task:
        return empty_payload()
    check_results = check_results or []
    cats = _categorize(timeline_events or [])
    agg = _aggregate_checks(check_results)

    summary_text = _summary_text(task, agg, len(timeline_events or []))

    sentences: List[Optional[str]] = []
    sentences.append(_block_main_state(cats))
    sentences.append(_block_divergence(cats, "IRS"))
    sentences.append(_block_divergence(cats, "RA"))
    sentences.append(_block_main_misalignment(cats))
    sentences.append(_block_channel_faults(cats))
    sentences.append(_block_misconfig(cats))   # 强信号
    sentences.append(_block_normal_selection(cats))
    sentences.append(_block_causal(cats))
    sentences = [s for s in sentences if s]

    # 兜底：六块都为空但仍有 detected → 列出具体 check_name 让人知道触发了哪一项
    if not sentences:
        if agg["total"] and agg["detected"] == 0:
            sentences.append("六项检查均「未发生」，主控、传感器选择、通道故障与因果链均无异常事件")
        elif agg["detected"]:
            detected_names = [
                (c.check_name or "").strip()
                for c in check_results
                if (c.overall_result or "") == "detected" and (c.check_name or "").strip()
            ]
            if detected_names:
                preview = "、".join(f"「{n}」" for n in detected_names[:3])
                more = f"（共 {len(detected_names)} 项）" if len(detected_names) > 3 else ""
                sentences.append(
                    f"已检测到事件的检查项：{preview}{more}，但本次未触发结构化的关键阶段叙述，"
                    f"可在下方完整时间线追溯具体报文"
                )
        elif agg["total"] == 0:
            sentences.append("未生成检查结果，无法形成过程描述")

    sentences = sentences[:_MAX_NARRATIVE_SENTENCES]
    timeline_narrative = join_sentences(sentences)

    tags = _build_tags(task, agg, cats, len(timeline_events or []))

    return {
        "summary_text": summary_text,
        "timeline_narrative": timeline_narrative,
        "summary_tags": tags,
    }
