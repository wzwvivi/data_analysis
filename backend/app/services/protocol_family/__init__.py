# -*- coding: utf-8 -*-
"""协议族注册表

每个设备协议家族（ARINC429 / CAN / RS422 / ...）提供一个 ``FamilyHandler``，
负责该家族的：
- normalize_spec：把 spec_json 规整（排序、去重、默认值）
- validate_spec：静态检查，返回 errors/warnings 列表
- diff_spec：两个 spec_json 的结构化 diff
- summarize_spec：UI 概览（label 数、端口数等）
- labels_view：以通用结构返回 labels/items 列表（给左树/搜索用，可空）

设备协议 handler 根据 spec.protocol_family 从 ``get_family_handler`` 取回实例。
"""
from typing import Dict

from .base import FamilyHandler, SpecDiff, SpecValidation
from .arinc429 import Arinc429FamilyHandler
from .can import CanFamilyHandler
from .rs422 import Rs422FamilyHandler

from ...models import (
    PROTOCOL_FAMILY_ARINC429,
    PROTOCOL_FAMILY_CAN,
    PROTOCOL_FAMILY_RS422,
)


_REGISTRY: Dict[str, FamilyHandler] = {
    PROTOCOL_FAMILY_ARINC429: Arinc429FamilyHandler(),
    PROTOCOL_FAMILY_CAN: CanFamilyHandler(),
    PROTOCOL_FAMILY_RS422: Rs422FamilyHandler(),
}


def get_family_handler(family: str) -> FamilyHandler:
    if family not in _REGISTRY:
        raise KeyError(f"未注册协议族：{family}")
    return _REGISTRY[family]


def list_families() -> Dict[str, FamilyHandler]:
    return dict(_REGISTRY)


__all__ = [
    "FamilyHandler",
    "SpecDiff",
    "SpecValidation",
    "get_family_handler",
    "list_families",
    "Arinc429FamilyHandler",
    "CanFamilyHandler",
    "Rs422FamilyHandler",
]
