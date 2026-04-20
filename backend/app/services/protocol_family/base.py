# -*- coding: utf-8 -*-
"""协议族 Handler 基类与数据结构"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


@dataclass
class SpecValidation:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "summary": {
                "is_ok": self.is_ok,
                "error_count": len(self.errors),
                "warning_count": len(self.warnings),
            },
        }


@dataclass
class SpecDiff:
    """家族无关的 diff 统一结构"""
    items_added: List[Dict[str, Any]] = field(default_factory=list)
    items_removed: List[Dict[str, Any]] = field(default_factory=list)
    items_changed: List[Dict[str, Any]] = field(default_factory=list)
    meta_changed: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items_added": list(self.items_added),
            "items_removed": list(self.items_removed),
            "items_changed": list(self.items_changed),
            "meta_changed": dict(self.meta_changed),
            "summary": {
                "added": len(self.items_added),
                "removed": len(self.items_removed),
                "changed": len(self.items_changed),
                "meta_changed": len(self.meta_changed),
            },
        }


@runtime_checkable
class FamilyHandler(Protocol):
    family: str  # 如 "arinc429"

    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def validate_spec(self, spec_json: Dict[str, Any]) -> SpecValidation:
        ...

    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        ...

    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        """UI 卡片用：label 数 / 端口数 / 更新时间等"""
        ...

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """以统一结构返回 items 列表，给设备树右侧的 label 列表/JSON 预览用"""
        ...

    def new_empty_spec(
        self,
        *,
        device_name: str,
        version_name: str,
        description: str | None = None,
    ) -> Dict[str, Any]:
        """新建设备时给出初始空 spec"""
        ...
