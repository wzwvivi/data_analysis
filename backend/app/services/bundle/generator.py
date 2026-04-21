# -*- coding: utf-8 -*-
"""Bundle 生成器

由 `protocol_activation_service.refresh_activation_pipeline` 在 CR 发布到
PendingCode 时调用。从数据库读取 `PortDefinition` / `FieldDefinition` 并
从 `event_rules.checksheet` 快照规则，渲染成版本化 JSON 落盘。

生成产物：
    backend/app/services/generated/v{version_id}/bundle.json
    backend/app/services/generated/v{version_id}/bundle.sha256  (可选：SHA256 hex)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import FieldDefinition, PortDefinition, ProtocolVersion
from ..protocol_service import resolve_port_family
from .loader import bundle_dir_for, bundle_path_for, invalidate_bundle_cache, sha256_path_for
from .schema import (
    BUNDLE_SCHEMA_VERSION,
    Bundle,
    BundleCanFrame,
    BundleCompareProfile,
    BundleContentCheck,
    BundleEventRule,
    BundleField,
    BundlePort,
    BundleRuleFilter,
    bundle_to_dict,
)

logger = logging.getLogger(__name__)


_LABEL_RE = re.compile(r"^L(\d{3})$", re.IGNORECASE)
_PARSERS_DIR = Path(__file__).resolve().parent.parent / "parsers"

# sidecar 数据文件名约定（与现有 parser 保持一致）
_CAN_SIDECAR_FILES = {
    "bms800v": "bms800v_data.json",
    "bms270v": "bms270v_data.json",
    "bpcu_empc": "bpcu_empc_data.json",
    "mcu": "mcu_data.json",
}


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


async def _load_version(db: AsyncSession, version_id: int) -> ProtocolVersion:
    res = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.id == version_id)
        .options(
            selectinload(ProtocolVersion.protocol),
            selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields),
        )
    )
    pv = res.scalar_one_or_none()
    if not pv:
        raise ValueError(f"协议版本 {version_id} 不存在")
    return pv


def _field_to_bundle(f: FieldDefinition) -> BundleField:
    return BundleField(
        name=f.field_name or "",
        offset=int(f.field_offset or 0),
        length=int(f.field_length or 0),
        data_type=(f.data_type or "bytes"),
        byte_order=(f.byte_order or "big"),
        scale_factor=float(f.scale_factor or 1.0),
        unit=f.unit,
        description=f.description,
    )


def _derive_arinc_labels(fields: List[BundleField]) -> List[str]:
    """从 field_name 里抽出形如 Lxxx 的 ARINC-429 label（去重保序）。"""
    seen: set = set()
    out: List[str] = []
    for f in fields:
        name = (f.name or "").strip()
        if not name:
            continue
        m = _LABEL_RE.match(name)
        if not m:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name.upper())
    return out


def _load_can_frames_for_family(family: str) -> Dict[int, List[BundleCanFrame]]:
    """为指定 CAN family 加载 port → [CanFrame] 映射。

    从 parsers/{family}_data.json 读取 port_map；如果文件不存在则返回空字典。
    这一步是折衷：CAN 的字段布局现在仍在 sidecar JSON 里，等后续把它们纳入
    ICD 导入再从 DB 读。先保证 bundle 里有，老 parser 不动。
    """
    fname = _CAN_SIDECAR_FILES.get(family)
    if not fname:
        return {}
    path = _PARSERS_DIR / fname
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Bundle] 读取 %s 失败: %s", path.name, exc)
        return {}
    port_map = data.get("port_map") or {}
    result: Dict[int, List[BundleCanFrame]] = {}
    for port_str, entries in port_map.items():
        try:
            port = int(port_str)
        except (TypeError, ValueError):
            continue
        frames: List[BundleCanFrame] = []
        for ent in entries or []:
            can_id = str(ent.get("can_id") or "").strip()
            if not can_id:
                continue
            try:
                offset = int(ent.get("offset") or 0)
            except (TypeError, ValueError):
                offset = 0
            frames.append(BundleCanFrame(
                can_id_hex=can_id,
                offset=offset,
                name=ent.get("name"),
            ))
        if frames:
            result[port] = frames
    return result


def _port_to_bundle(
    port: PortDefinition,
    can_frames_by_family: Dict[str, Dict[int, List[BundleCanFrame]]],
) -> BundlePort:
    bundle_fields = [
        _field_to_bundle(f)
        for f in sorted(port.fields or [], key=lambda x: (int(x.field_offset or 0), x.field_name or ""))
    ]
    family = resolve_port_family(port.port_number, db_family=port.protocol_family) or None
    can_frames: List[BundleCanFrame] = []
    if family and family in can_frames_by_family:
        can_frames = list(can_frames_by_family[family].get(port.port_number, []))
    raw_role = (getattr(port, "port_role", None) or "").strip() or None
    return BundlePort(
        port_number=int(port.port_number),
        protocol_family=family,
        port_role=raw_role,
        source_device=port.source_device,
        target_device=port.target_device,
        message_name=port.message_name,
        direction=port.data_direction,
        period_ms=float(port.period_ms) if port.period_ms is not None else None,
        fields=bundle_fields,
        arinc_labels=_derive_arinc_labels(bundle_fields),
        can_frames=can_frames,
    )


# ── 规则快照 ─────────────────────────────────────────────────────────────
def _snapshot_default_rules() -> List[BundleEventRule]:
    """把 event_rules.checksheet.Checksheet 的 CheckItem 列表投影成 BundleEventRule。

    现阶段规则仍以硬 offset 形式存在（Phase 4c 之后会改为字段名）；生成器原样
    快照，保留 offset 引用。等 Phase 4c 做完，规则源码会切到 field 引用，
    生成器也能直接把 field 原样快照进去——结构已经支持两种。
    """
    try:
        from ..event_rules.checksheet import Checksheet
    except Exception as exc:
        logger.warning("[Bundle] 无法导入 Checksheet，规则快照跳过: %s", exc)
        return []

    try:
        sheet = Checksheet()
    except Exception as exc:
        logger.warning("[Bundle] 实例化 Checksheet 失败，规则快照跳过: %s", exc)
        return []

    out: List[BundleEventRule] = []
    for item in sheet.get_check_items():
        try:
            out.append(_checkitem_to_bundle_rule(item))
        except Exception as exc:
            logger.warning("[Bundle] 规则 #%s 快照失败: %s", getattr(item, "sequence", "?"), exc)
    return out


def _dict_to_filter(d: Dict[str, Any]) -> BundleRuleFilter:
    return BundleRuleFilter(
        field=d.get("field"),
        offset=d.get("offset"),
        value=int(d.get("value") or 0),
    )


def _dict_to_content_check(d: Dict[str, Any]) -> BundleContentCheck:
    return BundleContentCheck(
        field=d.get("field"),
        offset=d.get("offset"),
        length=d.get("length"),
        decode=d.get("decode"),
        expected=d.get("expected"),
        expected_hex=d.get("expected_hex"),
    )


def _checkitem_to_bundle_rule(item: Any) -> BundleEventRule:
    return BundleEventRule(
        sequence=int(item.sequence),
        name=item.name,
        category=item.category,
        description=item.description,
        port=int(item.port),
        wireshark_filter=getattr(item, "wireshark_filter", "") or "",
        extra_ports=[int(p) for p in (item.extra_ports or [])],
        payload_filter=[_dict_to_filter(x) for x in (item.payload_filter or [])],
        state_prerequisite_filter=[
            _dict_to_filter(x) for x in (getattr(item, "state_prerequisite_filter", []) or [])
        ],
        detect_mode=getattr(item, "detect_mode", "first_match") or "first_match",
        expected_period_ms=item.expected_period_ms,
        period_tolerance_pct=float(getattr(item, "period_tolerance_pct", 0.30) or 0.30),
        content_checks=[_dict_to_content_check(x) for x in (item.content_checks or [])],
        response_port=item.response_port,
        response_filter=[_dict_to_filter(x) for x in (item.response_filter or [])],
        response_timeout_ms=int(getattr(item, "response_timeout_ms", 1000) or 1000),
        response_description=getattr(item, "response_description", "") or "",
        response_burst_count=int(getattr(item, "response_burst_count", 0) or 0),
        response_burst_threshold_ms=float(getattr(item, "response_burst_threshold_ms", 10) or 10),
        response_ports=[int(p) for p in (getattr(item, "response_ports", []) or [])],
        response_window_count=int(getattr(item, "response_window_count", 0) or 0),
        response_window_ms=float(getattr(item, "response_window_ms", 200) or 200),
    )


# ── 主入口 ─────────────────────────────────────────────────────────────
async def generate_bundle(
    db: AsyncSession, version_id: int
) -> Dict[str, Any]:
    """生成指定版本的 bundle.json，返回 artifact 元数据。

    { path, abs_path, sha256, bytes_written, generated_at, stats }
    """
    pv = await _load_version(db, version_id)

    # 预加载 CAN sidecar（按 family 分桶）
    can_frames_by_family: Dict[str, Dict[int, List[BundleCanFrame]]] = {}
    for fam in _CAN_SIDECAR_FILES.keys():
        can_frames_by_family[fam] = _load_can_frames_for_family(fam)

    ports_dict: Dict[int, BundlePort] = {}
    family_ports: Dict[str, List[int]] = {}
    port_to_family: Dict[int, str] = {}
    role_ports: Dict[str, List[int]] = {}
    port_to_role: Dict[int, str] = {}

    for port in sorted(pv.ports or [], key=lambda p: p.port_number):
        bp = _port_to_bundle(port, can_frames_by_family)
        ports_dict[bp.port_number] = bp
        if bp.protocol_family:
            family_ports.setdefault(bp.protocol_family, []).append(bp.port_number)
            port_to_family[bp.port_number] = bp.protocol_family
        if bp.port_role:
            role_ports.setdefault(bp.port_role, []).append(bp.port_number)
            port_to_role[bp.port_number] = bp.port_role

    for fam in family_ports:
        family_ports[fam] = sorted(set(family_ports[fam]))
    for role in role_ports:
        role_ports[role] = sorted(set(role_ports[role]))

    rules_default = _snapshot_default_rules()
    event_rules = {"default_v1": rules_default} if rules_default else {}

    bundle = Bundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        protocol_version_id=pv.id,
        protocol_version_name=pv.version or "",
        protocol_name=(pv.protocol.name if pv.protocol else "") or "",
        generated_at=datetime.utcnow(),
        ports=ports_dict,
        family_ports=family_ports,
        port_to_family=port_to_family,
        role_ports=role_ports,
        port_to_role=port_to_role,
        event_rules=event_rules,
        compare_profile=BundleCompareProfile(),
    )

    payload = bundle_to_dict(bundle)
    blob = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
    sha = _sha256_bytes(blob)

    out_json = bundle_path_for(pv.id)
    _atomic_write_bytes(out_json, blob)

    out_sha = sha256_path_for(pv.id)
    _atomic_write_bytes(out_sha, (sha + "  bundle.json\n").encode("utf-8"))

    invalidate_bundle_cache(pv.id)

    rel = f"backend/app/services/generated/v{pv.id}/bundle.json"
    return {
        "kind": "bundle",
        "path": rel,
        "abs_path": str(out_json),
        "sha256": sha,
        "bytes_written": len(blob),
        "generated_at": bundle.generated_at.isoformat() + "Z",
        "stats": {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "ports": len(ports_dict),
            "families": len(family_ports),
            "roles": len(role_ports),
            "event_rules_default_v1": len(rules_default),
        },
    }


def bundle_exists(version_id: int) -> bool:
    return bundle_path_for(int(version_id)).is_file()
