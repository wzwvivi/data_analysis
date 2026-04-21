# -*- coding: utf-8 -*-
"""Phase 1 向后兼容 shim。

原实现搬迁到 :mod:`.fms_event_analysis_service`。
下一个版本可直接删除这个文件。
"""
from .fms_event_analysis_service import (  # noqa: F401
    FmsEventAnalysisService,
    EventAnalysisService,
)

__all__ = ["FmsEventAnalysisService", "EventAnalysisService"]
