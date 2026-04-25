# -*- coding: utf-8 -*-
"""设备协议版本化 Bundle（MR: device ICD 与代码分离）

与 `services/bundle/` 并列：

| 维度        | services/bundle/             | services/device_bundle/（本模块）  |
| ----------- | ---------------------------- | ---------------------------------- |
| 源数据      | ProtocolVersion.ports/fields | DeviceProtocolVersion.spec_json    |
| 范围        | TSN 网络协议（端口/字段）     | 设备 ICD（ARINC429 Label 级细节）  |
| 落盘位置    | generated/v{id}/bundle.json  | generated_device/v{id}/bundle.json |
| 消费方      | parser_service / compare / event | 各设备 parser（adc/brake/…）   |

典型用法（parser 运行期）：

    from app.services.device_bundle import try_load_device_bundle
    dbundle = try_load_device_bundle(active_device_version_id)
    if dbundle:
        label_def = dbundle.label(0o164)  # → DeviceLabel 或 None

注意：port→labels 的路由信息归属 TSN 网络协议（``BundlePort.arinc_labels``），
不在设备 bundle 中体现；parser 应通过 TSN ``runtime_bundle.arinc_label_ints(port)``
查询端口路由。
"""
from .schema import (
    DEVICE_BUNDLE_SCHEMA_VERSION,
    DeviceBundle,
    DeviceLabel,
    DeviceBnrField,
    DeviceBcdPattern,
    DeviceBcdDigit,
    DeviceDiscreteBit,
    DeviceDiscreteBitGroup,
    DeviceSpecialField,
    device_bundle_to_dict,
    device_bundle_from_dict,
)
from .loader import (
    DeviceBundleNotFoundError,
    DeviceBundleIntegrityError,
    load_device_bundle,
    try_load_device_bundle,
    invalidate_device_bundle_cache,
    verify_device_bundle,
    device_bundle_path_for,
    device_bundle_cache_stats,
)
from .generator import generate_device_bundle, device_bundle_exists, build_device_bundle
from . import generator  # re-exported for publish pipeline

__all__ = [
    "generate_device_bundle",
    "device_bundle_exists",
    "build_device_bundle",
    "DEVICE_BUNDLE_SCHEMA_VERSION",
    "DeviceBundle",
    "DeviceLabel",
    "DeviceBnrField",
    "DeviceBcdPattern",
    "DeviceBcdDigit",
    "DeviceDiscreteBit",
    "DeviceDiscreteBitGroup",
    "DeviceSpecialField",
    "device_bundle_to_dict",
    "device_bundle_from_dict",
    "DeviceBundleNotFoundError",
    "DeviceBundleIntegrityError",
    "load_device_bundle",
    "try_load_device_bundle",
    "invalidate_device_bundle_cache",
    "verify_device_bundle",
    "device_bundle_path_for",
    "device_bundle_cache_stats",
    "generator",
]
