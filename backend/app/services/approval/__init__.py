# -*- coding: utf-8 -*-
"""通用审批引擎

M1：把 TSN 现有 submit/sign_off/publish 的模式提炼为通用 ``ChangeRequestEngine``，
    设备协议路径直接使用；TSN 路径保持原 ``protocol_publish_service`` 不变（等价化）。
M2+：把 TSN 路径也迁移到引擎。
"""
from .engine import (
    ChangeRequestEngine,
    DraftKindHandler,
    EnginePublishError,
    PublishedOutcome,
)

__all__ = [
    "ChangeRequestEngine",
    "DraftKindHandler",
    "EnginePublishError",
    "PublishedOutcome",
]
