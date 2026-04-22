# -*- coding: utf-8 -*-
"""通用占位协议 Handler：给 rs485 / mavlink / discrete / wireless / none 使用

这几种协议平台上暂时没有成熟的 spec 结构（有的是 PDF/docx 源协议，有的根本是
TSN 接收方占位）。统一用一个 frame-oriented 的最小结构：

    {
        "protocol_meta": {"name", "version", "description", "bus_type"},
        "frames": [ {"name": "...", "fields": [...] } ]
    }

实际编辑 UI 对这几个族暂时是只读展示（M1 不做 editor）。用它主要是让
CR / publish / Git 导出 等流程可以跑通。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .base import SpecDiff, SpecValidation


class GenericStubFamilyHandler:
    """非 429/CAN/422 的协议族都走这个兜底 handler。通过 family 字段自识别。"""

    def __init__(self, family: str, display_label: Optional[str] = None):
        self.family = family
        self.display_label = display_label or family

    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = copy.deepcopy(spec_json or {})
        meta = spec.setdefault("protocol_meta", {})
        meta.setdefault("bus_type", self.family)
        frames = spec.get("frames") or []
        if not isinstance(frames, list):
            frames = []
        norm: List[Dict[str, Any]] = []
        for f in frames:
            if not isinstance(f, dict):
                continue
            norm.append(
                {
                    "name": str(f.get("name") or "").strip() or "FRAME",
                    "description": f.get("description"),
                    "fields": list(f.get("fields") or []),
                }
            )
        norm.sort(key=lambda x: x.get("name") or "")
        spec["frames"] = norm
        return spec

    def validate_spec(self, spec_json: Dict[str, Any]) -> SpecValidation:
        out = SpecValidation()
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        if not meta.get("name"):
            out.errors.append("protocol_meta.name 不能为空")
        if not meta.get("version"):
            out.errors.append("protocol_meta.version 不能为空")
        return out

    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        out = SpecDiff()
        new_spec = self.normalize_spec(new or {})
        new_by = {f["name"]: f for f in new_spec.get("frames", []) if f.get("name")}
        if not old:
            for name in new_by:
                out.items_added.append({"key": name, "name": name})
            return out
        old_spec = self.normalize_spec(old)
        old_by = {f["name"]: f for f in old_spec.get("frames", []) if f.get("name")}
        for name, nf in new_by.items():
            if name not in old_by:
                out.items_added.append({"key": name, "name": name})
                continue
            of = old_by[name]
            changes: Dict[str, Dict[str, Any]] = {}
            for k in ("fields", "description"):
                if of.get(k) != nf.get(k):
                    changes[k] = {"old": of.get(k), "new": nf.get(k)}
            if changes:
                out.items_changed.append({"key": name, "name": name, "changes": changes})
        for name in old_by:
            if name not in new_by:
                out.items_removed.append({"key": name, "name": name})
        return out

    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        frames = spec.get("frames") or []
        field_cnt = sum(len(f.get("fields") or []) for f in frames if isinstance(f, dict))
        return {
            "family": self.family,
            "name": meta.get("name"),
            "version": meta.get("version"),
            "frame_count": len(frames),
            "field_count": field_cnt,
        }

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self.normalize_spec(spec_json or {})
        return [
            {
                "key": f.get("name"),
                "name": f.get("name"),
                "field_count": len(f.get("fields") or []),
            }
            for f in spec.get("frames", [])
        ]

    def new_empty_spec(
        self,
        *,
        device_name: str,
        version_name: str,
        description: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "protocol_meta": {
                "name": device_name,
                "version": version_name,
                "description": description or "",
                "bus_type": self.family,
            },
            "frames": [],
        }
