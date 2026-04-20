# -*- coding: utf-8 -*-
"""CAN 协议族 Handler（M1 stub，M2 完善 DBC 语义）

spec_json 占位结构：
{
    "protocol_meta": {"name", "version", "description"},
    "messages": [
        {
            "frame_id": 0x123,
            "frame_id_hex": "0x123",
            "name": "...",
            "dlc": 8,
            "cycle_ms": 10,
            "is_extended": false,
            "signals": [
                {"name", "start_bit", "length", "byte_order":"little"|"big",
                 "factor", "offset", "unit", "value_type":"unsigned"|"signed", "enum": {}}
            ]
        }
    ]
}
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .base import SpecDiff, SpecValidation


class CanFamilyHandler:
    family = "can"

    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = copy.deepcopy(spec_json or {})
        spec.setdefault("protocol_meta", {})
        msgs = spec.get("messages") or []
        if not isinstance(msgs, list):
            msgs = []
        norm_msgs: List[Dict[str, Any]] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            fid = m.get("frame_id")
            if isinstance(fid, str):
                try:
                    fid = int(fid, 0)
                except (TypeError, ValueError):
                    fid = None
            norm_msgs.append(
                {
                    "frame_id": fid,
                    "frame_id_hex": f"0x{fid:X}" if isinstance(fid, int) else None,
                    "name": str(m.get("name") or "").strip() or "UNKNOWN",
                    "dlc": m.get("dlc"),
                    "cycle_ms": m.get("cycle_ms"),
                    "is_extended": bool(m.get("is_extended")),
                    "signals": list(m.get("signals") or []),
                }
            )
        norm_msgs.sort(key=lambda x: (x.get("frame_id") if x.get("frame_id") is not None else 99999999))
        spec["messages"] = norm_msgs
        return spec

    def validate_spec(self, spec_json: Dict[str, Any]) -> SpecValidation:
        out = SpecValidation()
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        if not meta.get("name"):
            out.errors.append("protocol_meta.name 不能为空")
        if not meta.get("version"):
            out.errors.append("protocol_meta.version 不能为空")
        msgs = spec.get("messages") or []
        if not isinstance(msgs, list):
            out.errors.append("messages 必须是数组")
            return out
        seen: set[int] = set()
        for i, m in enumerate(msgs):
            prefix = f"messages[{i}]"
            if not isinstance(m, dict):
                out.errors.append(f"{prefix} 必须是对象")
                continue
            fid = m.get("frame_id")
            if fid is None:
                out.errors.append(f"{prefix}: frame_id 不能为空")
            elif isinstance(fid, int):
                if fid in seen:
                    out.errors.append(f"{prefix}: frame_id=0x{fid:X} 重复")
                seen.add(fid)
            if not m.get("name"):
                out.errors.append(f"{prefix}: name 不能为空")
        return out

    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        out = SpecDiff()
        new_spec = self.normalize_spec(new or {})
        new_by_id = {m["frame_id"]: m for m in new_spec.get("messages", []) if m.get("frame_id") is not None}
        if not old:
            for fid, m in new_by_id.items():
                out.items_added.append(
                    {"key": f"0x{fid:X}", "frame_id": fid, "name": m.get("name")}
                )
            return out
        old_spec = self.normalize_spec(old)
        old_by_id = {m["frame_id"]: m for m in old_spec.get("messages", []) if m.get("frame_id") is not None}

        for fid, new_m in new_by_id.items():
            if fid not in old_by_id:
                out.items_added.append(
                    {"key": f"0x{fid:X}", "frame_id": fid, "name": new_m.get("name")}
                )
                continue
            old_m = old_by_id[fid]
            changes: Dict[str, Dict[str, Any]] = {}
            for k in ("name", "dlc", "cycle_ms", "is_extended", "signals"):
                if old_m.get(k) != new_m.get(k):
                    changes[k] = {"old": old_m.get(k), "new": new_m.get(k)}
            if changes:
                out.items_changed.append(
                    {
                        "key": f"0x{fid:X}",
                        "frame_id": fid,
                        "name": new_m.get("name"),
                        "changes": changes,
                    }
                )
        for fid, old_m in old_by_id.items():
            if fid not in new_by_id:
                out.items_removed.append(
                    {"key": f"0x{fid:X}", "frame_id": fid, "name": old_m.get("name")}
                )
        return out

    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        msgs = spec.get("messages") or []
        sigs = sum(len(m.get("signals") or []) for m in msgs if isinstance(m, dict))
        return {
            "family": self.family,
            "name": meta.get("name"),
            "version": meta.get("version"),
            "message_count": len(msgs),
            "signal_count": sigs,
        }

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self.normalize_spec(spec_json or {})
        return [
            {
                "key": f"0x{m['frame_id']:X}" if isinstance(m.get("frame_id"), int) else str(m.get("frame_id")),
                "frame_id": m.get("frame_id"),
                "frame_id_hex": m.get("frame_id_hex"),
                "name": m.get("name"),
                "dlc": m.get("dlc"),
                "signal_count": len(m.get("signals") or []),
            }
            for m in spec.get("messages", [])
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
            "messages": [],
        }
