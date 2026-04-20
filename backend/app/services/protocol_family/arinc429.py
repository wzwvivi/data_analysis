# -*- coding: utf-8 -*-
"""ARINC429 协议族 Handler

spec_json 结构（移植自桌面 generator，精简）：
{
    "protocol_meta": {
        "name": "设备名",
        "version": "V2.0",
        "description": "...",
        "generated_at": "...",
    },
    "labels": [
        {
            "label_oct": "001",
            "label_dec": 1,
            "name": "...",
            "direction": "input" | "output",
            "sources": ["FCC", ...],
            "sdi": None | 0..3,
            "ssm_type": "bnr" | "discrete" | "bcd",
            "data_type": "...",
            "unit": "...",
            "range_desc": "...",
            "resolution": 0.1,
            "reserved_bits": "...",
            "notes": "...",
            "discrete_bits": {"11": "desc", ...},
            "special_fields": [{"name", "bits":[a,b], "type":"enum"|"uint"|"bcd", "values":{..}}, ...],
            "bnr_fields": [{"name", "data_bits":[a,b], "encoding":"bnr"|"bcd", "sign_bit":..., "resolution":..., "unit":...}, ...]
        },
        ...
    ]
}
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .base import FamilyHandler, SpecDiff, SpecValidation


# 与 TSN 的 FamilyHandler 保持一致的接口


class Arinc429FamilyHandler:
    family = "arinc429"

    # ──────────────── normalize ────────────────
    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = copy.deepcopy(spec_json or {})
        meta = spec.setdefault("protocol_meta", {})
        meta.setdefault("name", "")
        meta.setdefault("version", "")
        meta.setdefault("description", "")

        labels = spec.get("labels") or []
        if not isinstance(labels, list):
            labels = []

        normalized_labels: List[Dict[str, Any]] = []
        for lab in labels:
            if not isinstance(lab, dict):
                continue
            label_oct = str(lab.get("label_oct") or "").strip()
            if not label_oct:
                # 保留原顺序但标记为空 label；validate 时报错
                normalized_labels.append(
                    {**lab, "label_oct": "", "label_dec": None}
                )
                continue
            try:
                label_dec = int(label_oct, 8)
            except (TypeError, ValueError):
                label_dec = None
            new_lab = {
                "label_oct": label_oct,
                "label_dec": label_dec,
                "name": str(lab.get("name") or "").strip() or "Unknown",
                "direction": lab.get("direction") or "",
                "sources": list(lab.get("sources") or []),
                "sdi": lab.get("sdi"),
                "ssm_type": lab.get("ssm_type") or "bnr",
                "data_type": lab.get("data_type"),
                "unit": lab.get("unit"),
                "range_desc": lab.get("range_desc"),
                "resolution": lab.get("resolution"),
                "reserved_bits": lab.get("reserved_bits"),
                "notes": lab.get("notes"),
                "discrete_bits": dict(lab.get("discrete_bits") or {}),
                "special_fields": list(lab.get("special_fields") or []),
                "bnr_fields": list(lab.get("bnr_fields") or []),
            }
            normalized_labels.append(new_lab)

        normalized_labels.sort(
            key=lambda x: (x.get("label_dec") if x.get("label_dec") is not None else 9999, x.get("label_oct") or "")
        )
        spec["labels"] = normalized_labels
        return spec

    # ──────────────── validate ────────────────
    def validate_spec(self, spec_json: Dict[str, Any]) -> SpecValidation:
        out = SpecValidation()
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        if not meta.get("name"):
            out.errors.append("protocol_meta.name 不能为空")
        if not meta.get("version"):
            out.errors.append("protocol_meta.version 不能为空")

        labels = spec.get("labels") or []
        if not isinstance(labels, list):
            out.errors.append("labels 必须是数组")
            return out
        if not labels:
            out.warnings.append("labels 为空，当前设备无任何 Label 定义")

        seen_octs: set[str] = set()
        for idx, lab in enumerate(labels):
            prefix = f"labels[{idx}]"
            if not isinstance(lab, dict):
                out.errors.append(f"{prefix} 必须是对象")
                continue
            oct_val = str(lab.get("label_oct") or "").strip()
            if not oct_val:
                out.errors.append(f"{prefix}: label_oct 不能为空")
            else:
                try:
                    n = int(oct_val, 8)
                    if n > 255:
                        out.errors.append(
                            f"{prefix}: label_oct='{oct_val}' 超出范围（最大 377）"
                        )
                except (TypeError, ValueError):
                    out.errors.append(
                        f"{prefix}: label_oct='{oct_val}' 不是合法八进制"
                    )
                if oct_val in seen_octs:
                    out.errors.append(f"{prefix}: label_oct='{oct_val}' 重复")
                seen_octs.add(oct_val)

            if not lab.get("name"):
                out.errors.append(f"{prefix}: name 不能为空")

            for j, bf in enumerate(lab.get("bnr_fields") or []):
                bp = f"{prefix}.bnr_fields[{j}]"
                if not isinstance(bf, dict):
                    out.errors.append(f"{bp} 必须是对象")
                    continue
                if not bf.get("name"):
                    out.errors.append(f"{bp}: name 不能为空")
                data_bits = bf.get("data_bits")
                if not (isinstance(data_bits, (list, tuple)) and len(data_bits) == 2):
                    out.errors.append(f"{bp}: data_bits 必须是 [起始位, 结束位]")

            for j, sf in enumerate(lab.get("special_fields") or []):
                sp = f"{prefix}.special_fields[{j}]"
                if not isinstance(sf, dict):
                    out.errors.append(f"{sp} 必须是对象")
                    continue
                if not sf.get("name"):
                    out.errors.append(f"{sp}: name 不能为空")
                bits = sf.get("bits")
                if not (isinstance(bits, (list, tuple)) and len(bits) == 2):
                    out.errors.append(f"{sp}: bits 必须是 [起始位, 结束位]")

            for j, (bit_key, _desc) in enumerate(
                (lab.get("discrete_bits") or {}).items()
            ):
                dp = f"{prefix}.discrete_bits[{bit_key}]"
                try:
                    b = int(bit_key)
                    if b < 1 or b > 32:
                        out.errors.append(f"{dp}: bit 序号必须在 1..32 之间")
                except (TypeError, ValueError):
                    out.errors.append(f"{dp}: bit 序号必须为整数")
        return out

    # ──────────────── diff ────────────────
    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        out = SpecDiff()
        new_norm = self.normalize_spec(new or {})
        new_labels = {l["label_oct"]: l for l in new_norm.get("labels", []) if l.get("label_oct")}

        old_labels: Dict[str, Dict[str, Any]] = {}
        if old:
            old_norm = self.normalize_spec(old)
            old_labels = {l["label_oct"]: l for l in old_norm.get("labels", []) if l.get("label_oct")}

            old_meta = old_norm.get("protocol_meta") or {}
            new_meta = new_norm.get("protocol_meta") or {}
            for key in ("name", "version", "description"):
                ov = old_meta.get(key)
                nv = new_meta.get(key)
                if (ov or None) != (nv or None):
                    out.meta_changed[key] = {"old": ov, "new": nv}
        else:
            # 全量新增
            for oct_, lab in new_labels.items():
                out.items_added.append(
                    {"key": oct_, "label_oct": oct_, "name": lab.get("name")}
                )
            return out

        for oct_, new_lab in new_labels.items():
            if oct_ not in old_labels:
                out.items_added.append(
                    {"key": oct_, "label_oct": oct_, "name": new_lab.get("name")}
                )
                continue
            old_lab = old_labels[oct_]
            changes = self._label_diff(old_lab, new_lab)
            if changes:
                out.items_changed.append(
                    {
                        "key": oct_,
                        "label_oct": oct_,
                        "name": new_lab.get("name"),
                        "changes": changes,
                    }
                )

        for oct_, old_lab in old_labels.items():
            if oct_ not in new_labels:
                out.items_removed.append(
                    {"key": oct_, "label_oct": oct_, "name": old_lab.get("name")}
                )
        return out

    @staticmethod
    def _label_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        changed: Dict[str, Dict[str, Any]] = {}
        scalar_keys = (
            "name",
            "direction",
            "sdi",
            "ssm_type",
            "data_type",
            "unit",
            "range_desc",
            "resolution",
            "reserved_bits",
            "notes",
        )
        for k in scalar_keys:
            ov = old.get(k)
            nv = new.get(k)
            if (ov if ov is not None else None) != (nv if nv is not None else None):
                changed[k] = {"old": ov, "new": nv}

        for k in ("sources", "discrete_bits", "special_fields", "bnr_fields"):
            ov = old.get(k)
            nv = new.get(k)
            if ov != nv:
                changed[k] = {"old": ov, "new": nv}
        return changed

    # ──────────────── summarize / view / empty ────────────────
    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        labels = spec.get("labels") or []
        discrete_cnt = sum(len(l.get("discrete_bits") or {}) for l in labels if isinstance(l, dict))
        special_cnt = sum(len(l.get("special_fields") or []) for l in labels if isinstance(l, dict))
        bnr_cnt = sum(len(l.get("bnr_fields") or []) for l in labels if isinstance(l, dict))
        return {
            "family": self.family,
            "name": meta.get("name"),
            "version": meta.get("version"),
            "label_count": len(labels),
            "discrete_bit_count": discrete_cnt,
            "special_field_count": special_cnt,
            "bnr_field_count": bnr_cnt,
        }

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self.normalize_spec(spec_json or {})
        return [
            {
                "key": l.get("label_oct"),
                "label_oct": l.get("label_oct"),
                "label_dec": l.get("label_dec"),
                "name": l.get("name"),
                "direction": l.get("direction"),
                "data_type": l.get("data_type"),
                "unit": l.get("unit"),
                "discrete_count": len(l.get("discrete_bits") or {}),
                "special_count": len(l.get("special_fields") or []),
                "bnr_count": len(l.get("bnr_fields") or []),
            }
            for l in spec.get("labels", [])
            if l.get("label_oct")
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
            "labels": [],
        }
