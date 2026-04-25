# -*- coding: utf-8 -*-
"""自动飞行性能分析的领导级摘要 + 过程文字。

数据来源（``auto_flight_analysis.py``）：

- ``TouchdownAnalysisResult``：每次触地一行
  * ``vz_spread``：三套 IRS 测得垂直速度的离散度（m/s），越大越异常；
  * ``az_peak_spread``：三套 IRS 触地瞬时垂直加速度峰值的离散度（g）；
  * ``rating``：``normal`` / ``warning`` / ``critical``（业务侧由阈值决定）。

- ``SteadyStateAnalysisResult``：每段稳态飞行一行
  * ``alt_rms`` / ``lat_rms`` / ``spd_rms``：高度 / 横向 / 速度的稳态 RMS；
  * ``rating``：同上。

叙述策略：异常评级（rating != normal）整段提到底，并附上引发评级的关键指标，
让人一眼看到"哪个数值大"。``normal`` 项不细讲，只点数。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import empty_payload, fmt_time_str, join_sentences, status_tag


_MAX_NARRATIVE_SENTENCES = 7


def _fmt_duration_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{int(round(s))}s"
    if s < 3600:
        return f"{s / 60:.1f}min"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    return f"{h}h{m}min"


def _is_abnormal(rating: Optional[str]) -> bool:
    return (rating or "normal").lower() not in ("normal", "")


def _rating_zh(rating: Optional[str]) -> str:
    r = (rating or "normal").lower()
    return {
        "normal": "正常",
        "warning": "告警",
        "critical": "异常",
        "fail": "异常",
    }.get(r, rating or "正常")


def _touch_metric_str(t: Any) -> str:
    """触地评级附带关键指标。"""
    parts: List[str] = []
    spread = getattr(t, "vz_spread", None)
    if isinstance(spread, (int, float)):
        parts.append(f"VZ 散布 {spread:.2f} m/s")
    az_spread = getattr(t, "az_peak_spread", None)
    if isinstance(az_spread, (int, float)):
        parts.append(f"AZ 峰值散布 {az_spread:.2f} g")
    return "，".join(parts)


def _steady_metric_str(s: Any) -> str:
    parts: List[str] = []
    for label, attr, unit in (
        ("高度 RMS", "alt_rms", "m"),
        ("横向 RMS", "lat_rms", "m"),
        ("速度 RMS", "spd_rms", "m/s"),
    ):
        v = getattr(s, attr, None)
        if isinstance(v, (int, float)):
            parts.append(f"{label} {v:.2f}{unit}")
    return "，".join(parts)


def _summarize_touchdowns(rows: List[Any]) -> List[str]:
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: r.sequence or 0)
    abnormal = [r for r in rows if _is_abnormal(r.rating)]
    out: List[str] = []
    # 异常项整段叙述（最多 3 条）
    for r in abnormal[:3]:
        t = fmt_time_str(getattr(r, "touchdown_time", None), getattr(r, "touchdown_ts", None))
        metric = _touch_metric_str(r)
        metric_part = f"，{metric}" if metric else ""
        out.append(f"{t} 第 {r.sequence} 次触地评级 {_rating_zh(r.rating)}{metric_part}")
    if len(abnormal) > 3:
        out.append(f"另有 {len(abnormal) - 3} 次触地评级异常未一一展开")
    if not abnormal:
        # 全部正常：只点一句
        out.append(f"识别到 {len(rows)} 次触地，评级均为正常")
    elif len(abnormal) < len(rows):
        out.append(f"其余 {len(rows) - len(abnormal)} 次触地评级正常")
    return out


def _summarize_steady(rows: List[Any]) -> List[str]:
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: r.sequence or 0)
    abnormal = [r for r in rows if _is_abnormal(r.rating)]
    out: List[str] = []
    for r in abnormal[:2]:
        t0 = fmt_time_str(getattr(r, "start_time", None), getattr(r, "start_ts", None))
        t1 = fmt_time_str(getattr(r, "end_time", None), getattr(r, "end_ts", None))
        dur = _fmt_duration_seconds(getattr(r, "duration_s", None))
        mode = (r.mode_label or "稳态").strip()
        metric = _steady_metric_str(r)
        metric_part = f"，{metric}" if metric else ""
        out.append(
            f"{t0}–{t1} 第 {r.sequence} 段「{mode}」稳态飞行（{dur}）评级 "
            f"{_rating_zh(r.rating)}{metric_part}"
        )
    if len(abnormal) > 2:
        out.append(f"另有 {len(abnormal) - 2} 段稳态评级异常未一一展开")
    if not abnormal:
        # 全正常：合计
        modes = {}
        total_dur = 0.0
        for r in rows:
            mode = (r.mode_label or "稳态").strip()
            modes[mode] = modes.get(mode, 0) + 1
            d = getattr(r, "duration_s", None)
            if isinstance(d, (int, float)):
                total_dur += d
        modes_str = "、".join(f"{m}×{n}" for m, n in modes.items()) or f"共 {len(rows)} 段"
        out.append(
            f"识别到 {len(rows)} 段稳态飞行（{modes_str}，累计 "
            f"{_fmt_duration_seconds(total_dur)}），评级均为正常"
        )
    elif len(abnormal) < len(rows):
        out.append(f"其余 {len(rows) - len(abnormal)} 段稳态评级正常")
    return out


def _conclusion_sentence(touch_rows: List[Any], steady_rows: List[Any]) -> str:
    n_touch_bad = sum(1 for r in touch_rows if _is_abnormal(r.rating))
    n_steady_bad = sum(1 for r in steady_rows if _is_abnormal(r.rating))
    if not touch_rows and not steady_rows:
        return "本次自动飞行性能分析未识别到触地或稳态片段，请确认数据是否完整"
    parts = []
    if n_touch_bad:
        parts.append(f"{n_touch_bad} 次触地评级异常")
    if n_steady_bad:
        parts.append(f"{n_steady_bad} 段稳态评级异常")
    if parts:
        return "整体看，自动飞行过程可追溯；存在 " + "、".join(parts) + "，建议复核对应时段细节"
    return "整体看，触地与稳态过程平稳，未发现明显性能退化"


def _build_tags(task: Any, touch_rows: List[Any], steady_rows: List[Any]) -> List[Dict[str, str]]:
    touch_count = int(getattr(task, "touchdown_count", 0) or 0) or len(touch_rows)
    steady_count = int(getattr(task, "steady_count", 0) or 0) or len(steady_rows)
    tags: List[Dict[str, str]] = [status_tag(task.status)]
    if touch_count:
        tags.append({"label": f"触地 {touch_count}", "color": "blue"})
    if steady_count:
        tags.append({"label": f"稳态 {steady_count}", "color": "geekblue"})
    bad_touch = sum(1 for r in touch_rows if _is_abnormal(r.rating))
    bad_steady = sum(1 for r in steady_rows if _is_abnormal(r.rating))
    if bad_touch:
        tags.append({"label": f"触地异常 {bad_touch}", "color": "error"})
    if bad_steady:
        tags.append({"label": f"稳态异常 {bad_steady}", "color": "warning"})
    if (touch_count or steady_count) and not bad_touch and not bad_steady:
        tags.append({"label": "评级全部正常", "color": "success"})
    return tags


def _summary_text(task: Any, touch_rows: List[Any], steady_rows: List[Any]) -> str:
    if (task.status or "").lower() == "failed":
        return f"自动飞行性能分析失败：{task.error_message or '未知错误'}"
    n_touch = len(touch_rows)
    n_steady = len(steady_rows)
    if n_touch == 0 and n_steady == 0:
        return "自动飞行性能分析已完成，但未识别到触地或稳态片段。"
    bad_touch = sum(1 for r in touch_rows if _is_abnormal(r.rating))
    bad_steady = sum(1 for r in steady_rows if _is_abnormal(r.rating))
    if bad_touch == 0 and bad_steady == 0:
        return (
            f"自动飞行性能分析已完成，识别 {n_touch} 次触地、{n_steady} 段稳态飞行，"
            f"评级均为正常。"
        )
    return (
        f"自动飞行性能分析已完成，识别 {n_touch} 次触地、{n_steady} 段稳态飞行；"
        f"其中触地异常 {bad_touch} 次、稳态异常 {bad_steady} 段，需重点关注。"
    )


def build_auto_flight_narrative(
    task: Any,
    touch_rows: List[Any],
    steady_rows: List[Any],
) -> Dict[str, Any]:
    if not task:
        return empty_payload()
    touch_rows = touch_rows or []
    steady_rows = steady_rows or []

    summary_text = _summary_text(task, touch_rows, steady_rows)

    sentences: List[Optional[str]] = []
    for s in _summarize_touchdowns(touch_rows):
        sentences.append(s)
    for s in _summarize_steady(steady_rows):
        sentences.append(s)
    sentences = [s for s in sentences if s][:_MAX_NARRATIVE_SENTENCES - 1]
    sentences.append(_conclusion_sentence(touch_rows, steady_rows))
    timeline_narrative = join_sentences(sentences) if (touch_rows or steady_rows) else ""

    return {
        "summary_text": summary_text,
        "timeline_narrative": timeline_narrative,
        "summary_tags": _build_tags(task, touch_rows, steady_rows),
    }
