# -*- coding: utf-8 -*-
"""专项分析摘要生成器共用工具。"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional

import numpy as np


_TZ_BEIJING = timezone(timedelta(hours=8))


def safe_float(value: Any) -> Optional[float]:
    """把任意输入转 float，无效值返回 ``None``。"""
    try:
        v = float(value)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def fmt_time_str(time_str: Optional[str], ts: Optional[float] = None) -> str:
    """优先用现成的 ``time_str``；否则从 epoch 秒回推北京时间 ``HH:MM:SS``。"""
    if time_str and isinstance(time_str, str) and time_str.strip():
        return time_str.strip()
    f = safe_float(ts)
    if f is None:
        return "时间未知"
    try:
        return datetime.fromtimestamp(f, tz=timezone.utc).astimezone(_TZ_BEIJING).strftime("%H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "时间未知"


def join_sentences(parts: Iterable[Optional[str]]) -> str:
    """把多句话拼接成一段文字，过滤空串。"""
    out = []
    for p in parts:
        if not p:
            continue
        s = p.strip()
        if not s:
            continue
        if not s.endswith(("。", "；", ".", "!", "?", "！", "？")):
            s = s + "。"
        out.append(s)
    return "".join(out)


def status_tag(status: Optional[str]) -> Dict[str, str]:
    """统一把任务状态翻成 (label, color)。"""
    s = (status or "").lower()
    if s == "completed":
        return {"label": "已完成", "color": "success"}
    if s == "processing":
        return {"label": "进行中", "color": "processing"}
    if s == "failed":
        return {"label": "失败", "color": "error"}
    if s == "pending":
        return {"label": "待运行", "color": "warning"}
    return {"label": "未运行", "color": "default"}


def empty_payload() -> Dict[str, Any]:
    """模块尚未运行 / 数据缺失时的占位结构。"""
    return {
        "summary_text": "",
        "timeline_narrative": "",
        "summary_tags": [],
    }
