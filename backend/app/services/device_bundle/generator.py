# -*- coding: utf-8 -*-
"""设备协议 Bundle 生成器

由 `Arinc429PublishStrategy.publish` 在 DeviceProtocolVersion 落库之后调用。
从数据库读取一条 `DeviceProtocolVersion`（+ 关联 spec）的 `spec_json`，经
`Arinc429FamilyHandler.normalize_spec` 最终规整后，投影为
`DeviceBundle` 并落盘。

产物：
    backend/app/services/generated_device/v{device_version_id}/bundle.json
    backend/app/services/generated_device/v{device_version_id}/bundle.sha256
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import DeviceProtocolVersion
from ..protocol_family.arinc429 import Arinc429FamilyHandler
from .loader import (
    device_bundle_path_for,
    device_sha256_path_for,
    invalidate_device_bundle_cache,
)
from .schema import (
    DEVICE_BUNDLE_SCHEMA_VERSION,
    DeviceBcdDigit,
    DeviceBcdPattern,
    DeviceBnrField,
    DeviceBundle,
    DeviceDiscreteBit,
    DeviceDiscreteBitGroup,
    DeviceLabel,
    DeviceSpecialField,
    device_bundle_to_dict,
)

logger = logging.getLogger(__name__)


# ── IO helpers ───────────────────────────────────────────────────────────

def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── DB → model loaders ──────────────────────────────────────────────────

async def _load_device_version(
    db: AsyncSession, version_id: int
) -> DeviceProtocolVersion:
    res = await db.execute(
        select(DeviceProtocolVersion)
        .where(DeviceProtocolVersion.id == int(version_id))
        .options(selectinload(DeviceProtocolVersion.spec))
    )
    pv = res.scalar_one_or_none()
    if pv is None:
        raise LookupError(f"DeviceProtocolVersion#{version_id} 不存在")
    return pv


def _pick_parser_family(pv: DeviceProtocolVersion) -> Optional[str]:
    """从 ``DeviceProtocolVersion.parser_key`` 反查 ``ParserRegistry`` 里的
    ``protocol_family`` 作为 bundle 的 parser_family（Phase 7）。

    取不到时返回 None——此时 bundle 的 parser_family 留空，运行期 parser
    依然会按自己代码里的 ``protocol_family`` 类属性工作，互不影响。
    """
    from app.services.parsers import ParserRegistry  # 局部 import 避免循环

    key = (getattr(pv, "parser_key", None) or "").strip()
    if not key:
        return None
    meta = ParserRegistry.metadata(key)
    if not meta:
        return None
    fam = (meta.get("protocol_family") or "").strip()
    return fam or None


# ── spec_json → DeviceBundle 投影 ───────────────────────────────────────

def _coerce_bits(value: Any) -> List[int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return []
    try:
        return [int(value[0]), int(value[1])]
    except (TypeError, ValueError):
        return []


def _project_bnr_field(raw: Dict[str, Any]) -> DeviceBnrField:
    return DeviceBnrField(
        name=str(raw.get("name") or ""),
        data_bits=_coerce_bits(raw.get("data_bits")),
        encoding=str(raw.get("encoding") or "bnr"),
        sign_style=str(raw.get("sign_style") or "bit29_sign_magnitude"),
        sign_bit=_safe_int(raw.get("sign_bit")),
        resolution=_safe_float(raw.get("resolution")),
        unit=(str(raw["unit"]) if raw.get("unit") is not None else None),
        signed=raw.get("signed") if isinstance(raw.get("signed"), bool) else None,
    )


def _project_bcd_pattern(raw: Optional[Dict[str, Any]]) -> Optional[DeviceBcdPattern]:
    if not isinstance(raw, dict):
        return None
    digits: List[DeviceBcdDigit] = []
    for d in raw.get("digits") or []:
        if not isinstance(d, dict):
            continue
        digits.append(
            DeviceBcdDigit(
                name=str(d.get("name") or ""),
                data_bits=_coerce_bits(d.get("data_bits")),
                weight=_safe_float(d.get("weight")),
                mask=(str(d["mask"]) if d.get("mask") else None),
            )
        )
    sfs: Dict[str, int] = {}
    for k, v in (raw.get("sign_from_ssm") or {}).items():
        try:
            sfs[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    if not digits and not sfs and not raw.get("description"):
        return None
    return DeviceBcdPattern(
        digits=digits,
        sign_from_ssm=sfs,
        description=(str(raw["description"]) if raw.get("description") else None),
    )


def _project_discrete_bits(raw: Any) -> List[DeviceDiscreteBit]:
    """spec_json 里 discrete_bits 是 dict[str, str|dict]；投影成有序列表。"""
    if not isinstance(raw, dict):
        return []
    out: List[DeviceDiscreteBit] = []
    for key, val in raw.items():
        try:
            bit = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(val, dict):
            values = {}
            raw_values = val.get("values") or {}
            if isinstance(raw_values, dict):
                for k2, v2 in raw_values.items():
                    values[str(k2)] = str(v2)
            out.append(
                DeviceDiscreteBit(
                    bit=bit,
                    name=str(val.get("name") or ""),
                    cn=str(val.get("cn") or ""),
                    values=values,
                    raw_desc=(
                        str(val["desc"])
                        if isinstance(val.get("desc"), str) and val["desc"]
                        else None
                    ),
                )
            )
        else:
            # 老数据：val 是字符串描述
            out.append(
                DeviceDiscreteBit(
                    bit=bit,
                    name="",
                    cn="",
                    values={},
                    raw_desc=str(val) if val not in (None, "") else None,
                )
            )
    out.sort(key=lambda x: x.bit)
    return out


def _project_discrete_bit_groups(raw: Any) -> List[DeviceDiscreteBitGroup]:
    if not isinstance(raw, list):
        return []
    out: List[DeviceDiscreteBitGroup] = []
    for g in raw:
        if not isinstance(g, dict):
            continue
        values_raw = g.get("values") or {}
        values: Dict[str, str] = {}
        if isinstance(values_raw, dict):
            for k, v in values_raw.items():
                values[str(k)] = str(v)
        out.append(
            DeviceDiscreteBitGroup(
                name=str(g.get("name") or ""),
                cn=str(g.get("cn") or ""),
                bits=_coerce_bits(g.get("bits")),
                values=values,
            )
        )
    return out


def _project_special_field(raw: Dict[str, Any]) -> DeviceSpecialField:
    bits_raw = raw.get("data_bits")
    data_bits = _coerce_bits(bits_raw) if bits_raw is not None else None
    if data_bits == []:
        data_bits = None
    values_raw = raw.get("values") or {}
    values: Dict[str, str] = {}
    if isinstance(values_raw, dict):
        for k, v in values_raw.items():
            values[str(k)] = str(v)
    return DeviceSpecialField(
        name=str(raw.get("name") or ""),
        data_bits=data_bits,
        encoding=str(raw.get("encoding") or raw.get("type") or "binary"),
        values=values,
        description=(str(raw["description"]) if raw.get("description") else None),
        unit=(str(raw["unit"]) if raw.get("unit") else None),
    )


def _project_port_overrides(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for port, ov in raw.items():
        if not isinstance(ov, dict):
            continue
        try:
            port_key = str(int(str(port).strip()))
        except (TypeError, ValueError):
            port_key = str(port)
        out[port_key] = dict(ov)
    return out


def _project_ssm_semantics(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _project_label(raw: Dict[str, Any]) -> Optional[DeviceLabel]:
    label_oct = str(raw.get("label_oct") or "").strip()
    if not label_oct:
        return None
    label_dec = raw.get("label_dec")
    if not isinstance(label_dec, int):
        try:
            label_dec = int(label_oct, 8)
        except (TypeError, ValueError):
            return None

    bnr_fields = [
        _project_bnr_field(f) for f in (raw.get("bnr_fields") or []) if isinstance(f, dict)
    ]
    special_fields = [
        _project_special_field(f)
        for f in (raw.get("special_fields") or [])
        if isinstance(f, dict)
    ]

    return DeviceLabel(
        label_oct=label_oct.zfill(3),
        label_dec=int(label_dec),
        name=str(raw.get("name") or "Unknown"),
        cn=str(raw.get("cn") or ""),
        direction=str(raw.get("direction") or ""),
        sources=[str(s) for s in (raw.get("sources") or [])],
        sdi=_safe_int(raw.get("sdi")),
        ssm_type=str(raw.get("ssm_type") or "bnr"),
        data_type=(str(raw["data_type"]) if raw.get("data_type") else None),
        unit=(str(raw["unit"]) if raw.get("unit") else None),
        range_desc=(str(raw["range_desc"]) if raw.get("range_desc") else None),
        resolution=_safe_float(raw.get("resolution")),
        reserved_bits=(str(raw["reserved_bits"]) if raw.get("reserved_bits") else None),
        notes=(str(raw["notes"]) if raw.get("notes") else None),
        bnr_fields=bnr_fields,
        bcd_pattern=_project_bcd_pattern(raw.get("bcd_pattern")),
        discrete_bits=_project_discrete_bits(raw.get("discrete_bits")),
        discrete_bit_groups=_project_discrete_bit_groups(raw.get("discrete_bit_groups")),
        special_fields=special_fields,
        port_overrides=_project_port_overrides(raw.get("port_overrides")),
        ssm_semantics=_project_ssm_semantics(raw.get("ssm_semantics")),
    )


# NOTE: port_routing（UDP 端口 → labels）归属 TSN 网络协议（BundlePort.arinc_labels），
# 不再由设备 bundle 承载。旧版 spec_json 里可能残留 port_routing 字段，但本模块不再
# 向 DeviceBundle 投影；parser 运行期从 TSN runtime_bundle 读取。


def _safe_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def build_device_bundle(
    pv: DeviceProtocolVersion,
    spec_json: Dict[str, Any],
    *,
    parser_family: Optional[str],
) -> DeviceBundle:
    """纯投影函数：给定规范化后的 spec_json，生成 DeviceBundle。"""
    labels_dict: Dict[int, DeviceLabel] = {}
    for raw in spec_json.get("labels") or []:
        if not isinstance(raw, dict):
            continue
        lab = _project_label(raw)
        if lab is not None:
            labels_dict[lab.label_dec] = lab

    spec = pv.spec if getattr(pv, "spec", None) else None
    return DeviceBundle(
        schema_version=DEVICE_BUNDLE_SCHEMA_VERSION,
        device_version_id=int(pv.id),
        device_version_name=str(pv.version_name or ""),
        device_spec_id=int(pv.spec_id or 0),
        device_id=str(getattr(spec, "device_id", "") or "") if spec else "",
        device_name=str(getattr(spec, "device_name", "") or "") if spec else "",
        protocol_family=(str(getattr(spec, "protocol_family", "arinc429")) if spec else "arinc429"),
        parser_family=parser_family,
        ata_code=(str(getattr(spec, "ata_code", "")) or None) if spec else None,
        generated_at=datetime.utcnow(),
        labels=labels_dict,
    )


# ── 主入口 ───────────────────────────────────────────────────────────────

async def generate_device_bundle(
    db: AsyncSession, device_version_id: int
) -> Dict[str, Any]:
    """生成指定 DeviceProtocolVersion 的 device_bundle.json。返回 artifact 元数据。

    { path, abs_path, sha256, bytes_written, generated_at, stats }
    """
    pv = await _load_device_version(db, device_version_id)

    handler = Arinc429FamilyHandler()
    # 防御性：入库时已经 normalize 过，这里再 normalize 一次确保新字段齐全
    try:
        normalized = handler.normalize_spec(dict(pv.spec_json or {}))
    except Exception as exc:
        # normalize 失败则回落到原始 spec_json（parser 需要能读出能看到的任何内容）
        logger.warning(
            "[DeviceBundle] v%s normalize_spec 失败，回落原始 spec_json: %s",
            pv.id,
            exc,
        )
        normalized = dict(pv.spec_json or {})

    parser_family = _pick_parser_family(pv)
    bundle = build_device_bundle(pv, normalized, parser_family=parser_family)

    payload = device_bundle_to_dict(bundle)
    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    sha = _sha256_bytes(blob)

    out_json = device_bundle_path_for(pv.id)
    _atomic_write_bytes(out_json, blob)

    out_sha = device_sha256_path_for(pv.id)
    _atomic_write_bytes(out_sha, (sha + "  bundle.json\n").encode("utf-8"))

    invalidate_device_bundle_cache(pv.id)

    rel = f"backend/app/services/generated_device/v{pv.id}/bundle.json"
    logger.info(
        "[DeviceBundle] generated v%s device=%s(%s) parser=%s labels=%s bytes=%s",
        pv.id,
        bundle.device_id,
        bundle.device_name,
        bundle.parser_family,
        len(bundle.labels),
        len(blob),
    )
    return {
        "kind": "device_bundle",
        "path": rel,
        "abs_path": str(out_json),
        "sha256": sha,
        "bytes_written": len(blob),
        "generated_at": bundle.generated_at.isoformat() + "Z",
        "stats": {
            "schema_version": DEVICE_BUNDLE_SCHEMA_VERSION,
            "device_id": bundle.device_id,
            "device_name": bundle.device_name,
            "parser_family": bundle.parser_family,
            "labels": len(bundle.labels),
            "bnr_fields": sum(len(l.bnr_fields) for l in bundle.labels.values()),
            "discrete_bits": sum(len(l.discrete_bits) for l in bundle.labels.values()),
            "discrete_bit_groups": sum(
                len(l.discrete_bit_groups) for l in bundle.labels.values()
            ),
            "bcd_pattern_count": sum(
                1 for l in bundle.labels.values() if l.bcd_pattern is not None
            ),
            "port_override_count": sum(
                len(l.port_overrides) for l in bundle.labels.values()
            ),
            "ssm_semantics_count": sum(
                1 for l in bundle.labels.values() if l.ssm_semantics
            ),
        },
    }


def device_bundle_exists(device_version_id: int) -> bool:
    return device_bundle_path_for(int(device_version_id)).is_file()
