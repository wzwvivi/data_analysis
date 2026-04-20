# -*- coding: utf-8 -*-
"""RS422 协议族 Handler（M1 stub）

spec_json 占位结构：
{
    "protocol_meta": {"name", "version", "description"},
    "frames": [
        {
            "name": "...",
            "header": "0xAA55",
            "trailer": "0x55AA",
            "length": 16,
            "fields": [
                {"name", "offset", "length", "data_type", "endian":"big"|"little",
                 "scale", "unit", "description"}
            ],
            "checksum": {"type":"crc16"|"sum8"|"none", "offset":14, "length":2}
        }
    ]
}
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .base import SpecDiff, SpecValidation


class Rs422FamilyHandler:
    family = "rs422"

    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = copy.deepcopy(spec_json or {})
        spec.setdefault("protocol_meta", {})
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
                    "header": f.get("header"),
                    "trailer": f.get("trailer"),
                    "length": f.get("length"),
                    "fields": list(f.get("fields") or []),
                    "checksum": f.get("checksum") or {"type": "none"},
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
        frames = spec.get("frames") or []
        if not isinstance(frames, list):
            out.errors.append("frames 必须是数组")
            return out
        seen: set[str] = set()
        for i, f in enumerate(frames):
            prefix = f"frames[{i}]"
            if not isinstance(f, dict):
                out.errors.append(f"{prefix} 必须是对象")
                continue
            name = str(f.get("name") or "").strip()
            if not name:
                out.errors.append(f"{prefix}: name 不能为空")
            elif name in seen:
                out.errors.append(f"{prefix}: frame name='{name}' 重复")
            seen.add(name)
        return out

    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        out = SpecDiff()
        new_spec = self.normalize_spec(new or {})
        new_by_name = {f["name"]: f for f in new_spec.get("frames", []) if f.get("name")}
        if not old:
            for name, f in new_by_name.items():
                out.items_added.append({"key": name, "name": name})
            return out
        old_spec = self.normalize_spec(old)
        old_by_name = {f["name"]: f for f in old_spec.get("frames", []) if f.get("name")}
        for name, new_f in new_by_name.items():
            if name not in old_by_name:
                out.items_added.append({"key": name, "name": name})
                continue
            old_f = old_by_name[name]
            changes: Dict[str, Dict[str, Any]] = {}
            for k in ("header", "trailer", "length", "fields", "checksum"):
                if old_f.get(k) != new_f.get(k):
                    changes[k] = {"old": old_f.get(k), "new": new_f.get(k)}
            if changes:
                out.items_changed.append({"key": name, "name": name, "changes": changes})
        for name, old_f in old_by_name.items():
            if name not in new_by_name:
                out.items_removed.append({"key": name, "name": name})
        return out

    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        frames = spec.get("frames") or []
        fields_cnt = sum(len(f.get("fields") or []) for f in frames if isinstance(f, dict))
        return {
            "family": self.family,
            "name": meta.get("name"),
            "version": meta.get("version"),
            "frame_count": len(frames),
            "field_count": fields_cnt,
        }

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self.normalize_spec(spec_json or {})
        return [
            {
                "key": f.get("name"),
                "name": f.get("name"),
                "length": f.get("length"),
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
            },
            "frames": [],
        }
