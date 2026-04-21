# -*- coding: utf-8 -*-
"""Phase 1 向后兼容 shim。

原实现搬迁到 :mod:`.fms_event_analysis`，此处只保留老的导入路径别名。
下一个版本可直接删除这个文件。
"""
from .fms_event_analysis import (
    FmsEventAnalysisTask,
    FmsEventCheckResult,
    FmsEventTimelineEvent,
    EventAnalysisTask,
    EventCheckResult,
    EventTimelineEvent,
)

__all__ = [
    "FmsEventAnalysisTask",
    "FmsEventCheckResult",
    "FmsEventTimelineEvent",
    "EventAnalysisTask",
    "EventCheckResult",
    "EventTimelineEvent",
]
