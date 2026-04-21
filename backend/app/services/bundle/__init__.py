# -*- coding: utf-8 -*-
"""版本化 Bundle 模块（MR4：代码与数据分离）

Bundle 是按 ProtocolVersion 版本号落盘的 JSON 数据包，承载三类模块运行时需要
的 ICD 衍生数据：

- parser_service / parsers/*        —— 字段布局、family→ports、port→arinc_labels
- compare_service（TSN 异常检查）   —— 端口元数据、period_ms、阈值 profile
- event_analysis_service            —— 事件规则（按字段名引用 offset）

Bundle 文件位置：
    backend/app/services/generated/v{N}/bundle.json

与 port_registry.py 并列，由 `protocol_activation_service.refresh_activation_pipeline`
在 CR 发布到 PendingCode 时自动生成。
"""
from .schema import (
    Bundle,
    BundleField,
    BundlePort,
    BundleRule,
    BundleRuleFilter,
    BundleContentCheck,
    BundleCompareProfile,
    BundleCanFrame,
    BundleEventRule,
    BUNDLE_SCHEMA_VERSION,
)
from .loader import (
    BundleNotFoundError,
    BundleIntegrityError,
    load_bundle,
    try_load_bundle,
    invalidate_bundle_cache,
    verify_bundle,
    bundle_path_for,
    cache_stats,
)
from . import generator  # re-exported for activation pipeline

__all__ = [
    "Bundle",
    "BundleField",
    "BundlePort",
    "BundleRule",
    "BundleRuleFilter",
    "BundleContentCheck",
    "BundleCompareProfile",
    "BundleCanFrame",
    "BundleEventRule",
    "BUNDLE_SCHEMA_VERSION",
    "BundleNotFoundError",
    "BundleIntegrityError",
    "load_bundle",
    "try_load_bundle",
    "invalidate_bundle_cache",
    "verify_bundle",
    "bundle_path_for",
    "cache_stats",
    "generator",
]
