# -*- coding: utf-8 -*-
"""ARINC429 设备树与 Label 管理（异步）"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    Arinc429Device,
    Arinc429DeviceProtocolVersion,
    Arinc429Label,
    Arinc429VersionHistory,
)


def _slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]", "_", (text or "").strip())
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return (s[:max_len] if s else "node")


def _unique_device_key(base: str) -> str:
    b = _slugify(base, 80) or "device"
    return f"{b}_{uuid.uuid4().hex[:8]}"


async def get_device_by_key(db: AsyncSession, device_id: str) -> Optional[Arinc429Device]:
    r = await db.execute(select(Arinc429Device).where(Arinc429Device.device_id == device_id))
    return r.scalar_one_or_none()


async def get_device_by_pk(db: AsyncSession, pk: int) -> Optional[Arinc429Device]:
    r = await db.execute(select(Arinc429Device).where(Arinc429Device.id == pk))
    return r.scalar_one_or_none()


def _node_to_dict(
    d: Arinc429Device,
    children: List[Dict[str, Any]],
    versions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": d.id,
        "device_id": d.device_id,
        "name": d.name,
        "parent_id": d.parent_id,
        "is_device": d.is_device,
        "device_version": d.device_version,
        "current_version_name": d.current_version_name,
        "description": d.description,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "children": children,
        "versions": versions,
    }


async def get_device_tree(db: AsyncSession) -> List[Dict[str, Any]]:
    r = await db.execute(
        select(Arinc429Device).options(
            selectinload(Arinc429Device.protocol_versions),
        ).order_by(Arinc429Device.id)
    )
    rows = list(r.scalars().unique().all())
    by_id = {d.id: d for d in rows}

    ver_by_dev: Dict[int, List[Dict[str, Any]]] = {}
    for d in rows:
        if d.protocol_versions:
            ver_by_dev[d.id] = [
                {"id": v.id, "name": v.version_name, "version": v.version}
                for v in d.protocol_versions
            ]
        else:
            ver_by_dev[d.id] = []

    memo: Dict[int, Dict[str, Any]] = {}

    def build(did: int) -> Dict[str, Any]:
        if did in memo:
            return memo[did]
        d = by_id[did]
        ch_ids = [x.id for x in rows if x.parent_id == did]
        children = [build(cid) for cid in ch_ids]
        node = _node_to_dict(d, children, ver_by_dev.get(d.id, []))
        memo[did] = node
        return node

    roots = [d.id for d in rows if d.parent_id is None]
    return [build(rid) for rid in roots]


async def create_system(
    db: AsyncSession,
    *,
    name: str,
    parent_id: Optional[int] = None,
    description: Optional[str] = None,
) -> Arinc429Device:
    if parent_id is not None:
        p = await get_device_by_pk(db, parent_id)
        if not p:
            raise ValueError("父节点不存在")
    key = _unique_device_key(name)
    # 避免极端碰撞
    while await get_device_by_key(db, key):
        key = _unique_device_key(name)
    now = datetime.utcnow()
    row = Arinc429Device(
        device_id=key,
        name=name.strip(),
        parent_id=parent_id,
        is_device=False,
        device_version="V1.0",
        current_version_name=None,
        description=description,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def create_leaf_device(
    db: AsyncSession,
    *,
    name: str,
    parent_id: int,
    device_id: Optional[str] = None,
    description: Optional[str] = None,
) -> Arinc429Device:
    p = await get_device_by_pk(db, parent_id)
    if not p:
        raise ValueError("父节点不存在")
    key = (device_id or "").strip() or _unique_device_key(name)
    if await get_device_by_key(db, key):
        raise ValueError("device_id 已存在")
    now = datetime.utcnow()
    row = Arinc429Device(
        device_id=key,
        name=name.strip(),
        parent_id=parent_id,
        is_device=True,
        device_version="V1.0",
        current_version_name="V1.0",
        description=description,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    pv = Arinc429DeviceProtocolVersion(
        device_id=row.id,
        version_name="V1.0",
        version="V1.0",
    )
    db.add(pv)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_device_by_key(db: AsyncSession, device_id: str) -> bool:
    d = await get_device_by_key(db, device_id)
    if not d:
        return False
    await db.execute(delete(Arinc429Device).where(Arinc429Device.id == d.id))
    await db.commit()
    return True


async def _resolve_protocol_version_id(
    db: AsyncSession,
    device: Arinc429Device,
    protocol_version_id: Optional[int],
) -> Optional[int]:
    if protocol_version_id is not None:
        r = await db.execute(
            select(Arinc429DeviceProtocolVersion).where(
                Arinc429DeviceProtocolVersion.id == protocol_version_id,
                Arinc429DeviceProtocolVersion.device_id == device.id,
            )
        )
        v = r.scalar_one_or_none()
        if not v:
            raise ValueError("协议版本不属于该设备")
        return v.id
    name = device.current_version_name
    if not name:
        return None
    r = await db.execute(
        select(Arinc429DeviceProtocolVersion).where(
            Arinc429DeviceProtocolVersion.device_id == device.id,
            Arinc429DeviceProtocolVersion.version_name == name,
        )
    )
    v = r.scalar_one_or_none()
    return v.id if v else None


def _label_row_to_api(row: Arinc429Label) -> Dict[str, Any]:
    return {
        "id": row.id,
        "label_oct": row.label_oct,
        "name": row.name,
        "direction": row.direction,
        "sources": row.sources if row.sources is not None else [],
        "data_type": row.data_type,
        "unit": row.unit,
        "range": row.range_desc,
        "resolution": row.resolution,
        "reserved_bits": row.reserved_bits,
        "notes": row.notes,
        "discrete_bits": row.discrete_bits if row.discrete_bits is not None else {},
        "special_fields": row.special_fields if row.special_fields is not None else [],
        "bnr_fields": row.bnr_fields if row.bnr_fields is not None else [],
        "protocol_version_id": row.protocol_version_id,
    }


async def list_labels(
    db: AsyncSession,
    device_id: str,
    protocol_version_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    device = await get_device_by_key(db, device_id)
    if not device or not device.is_device:
        raise ValueError("设备不存在或不是叶子设备")
    vid = await _resolve_protocol_version_id(db, device, protocol_version_id)
    q = select(Arinc429Label).where(Arinc429Label.device_id == device.id)
    if vid is not None:
        q = q.where(Arinc429Label.protocol_version_id == vid)
    else:
        q = q.where(Arinc429Label.protocol_version_id.is_(None))
    q = q.order_by(Arinc429Label.label_oct)
    r = await db.execute(q)
    rows = list(r.scalars().all())
    return [_label_row_to_api(x) for x in rows]


def _payload_to_label_fields(payload: Any) -> Dict[str, Any]:
    """Accept dict or Pydantic-like object."""
    if hasattr(payload, "model_dump"):
        d = payload.model_dump(by_alias=True, mode="python")
    else:
        d = dict(payload)
    return {
        "label_oct": str(d.get("label_oct", "") or ""),
        "name": str(d.get("name", "") or ""),
        "direction": d.get("direction") or "",
        "sources": d.get("sources") if d.get("sources") is not None else [],
        "data_type": d.get("data_type") or "",
        "unit": d.get("unit") or "",
        "range_desc": d.get("range") or d.get("range_value") or d.get("range_desc") or "",
        "resolution": d.get("resolution"),
        "reserved_bits": d.get("reserved_bits") or "",
        "notes": d.get("notes") or "",
        "discrete_bits": d.get("discrete_bits") if d.get("discrete_bits") is not None else {},
        "special_fields": d.get("special_fields")
        if d.get("special_fields") is not None
        else [],
        "bnr_fields": d.get("bnr_fields") if d.get("bnr_fields") is not None else [],
    }


async def save_labels(
    db: AsyncSession,
    device_id: str,
    labels: List[Any],
    *,
    protocol_version_id: Optional[int] = None,
    updated_by: Optional[str] = None,
    change_summary: Optional[str] = None,
    bump_version: bool = False,
) -> Tuple[int, Optional[str]]:
    device = await get_device_by_key(db, device_id)
    if not device or not device.is_device:
        raise ValueError("设备不存在或不是叶子设备")

    vid = await _resolve_protocol_version_id(db, device, protocol_version_id)
    if vid is None and device.current_version_name:
        r = await db.execute(
            select(Arinc429DeviceProtocolVersion).where(
                Arinc429DeviceProtocolVersion.device_id == device.id,
                Arinc429DeviceProtocolVersion.version_name == device.current_version_name,
            )
        )
        pv = r.scalar_one_or_none()
        if pv:
            vid = pv.id

    old_snapshot = await list_labels(db, device_id, protocol_version_id=vid)

    new_ver_label: Optional[str] = None
    if bump_version:
        m = re.match(r"^V(\d+)(?:\.(\d+))?$", device.device_version or "V1.0")
        if m:
            major = int(m.group(1))
            minor = int(m.group(2) or 0) + 1
            new_ver = f"V{major}.{minor}"
        else:
            new_ver = f"V{datetime.utcnow().strftime('%Y%m%d%H%M')}"
        device.device_version = new_ver
        device.current_version_name = new_ver
        new_ver_label = new_ver
        npv = Arinc429DeviceProtocolVersion(
            device_id=device.id,
            version_name=new_ver,
            version=new_ver,
        )
        db.add(npv)
        await db.flush()
        vid = npv.id

    if vid is not None:
        await db.execute(
            delete(Arinc429Label).where(
                Arinc429Label.device_id == device.id,
                Arinc429Label.protocol_version_id == vid,
            )
        )
    else:
        await db.execute(
            delete(Arinc429Label).where(
                Arinc429Label.device_id == device.id,
                Arinc429Label.protocol_version_id.is_(None),
            )
        )

    now = datetime.utcnow()
    for pl in labels:
        f = _payload_to_label_fields(pl)
        if not f["label_oct"] and not f["name"]:
            continue
        db.add(
            Arinc429Label(
                device_id=device.id,
                protocol_version_id=vid,
                label_oct=f["label_oct"],
                name=f["name"] or f["label_oct"],
                direction=f["direction"] or None,
                sources=f["sources"],
                data_type=f["data_type"] or None,
                unit=f["unit"] or None,
                range_desc=f["range_desc"] or None,
                resolution=f["resolution"],
                reserved_bits=f["reserved_bits"] or None,
                notes=f["notes"] or None,
                discrete_bits=f["discrete_bits"],
                special_fields=f["special_fields"],
                bnr_fields=f["bnr_fields"],
                created_at=now,
                updated_at=now,
            )
        )

    await db.flush()
    new_snapshot = await list_labels(db, device_id, protocol_version_id=vid)

    hist_ver = new_ver_label or (device.device_version or "V1.0")
    hist = Arinc429VersionHistory(
        device_id=device.id,
        version=hist_ver,
        updated_at=now,
        updated_by=updated_by,
        change_summary=change_summary or "保存 Labels",
        diff_summary={"before_count": len(old_snapshot), "after_count": len(new_snapshot)},
        label_snapshot=new_snapshot,
        label_count=len(new_snapshot),
    )
    db.add(hist)
    device.updated_at = now
    await db.commit()
    return len(new_snapshot), new_ver_label


async def delete_label(
    db: AsyncSession,
    device_id: str,
    label_pk: int,
) -> bool:
    device = await get_device_by_key(db, device_id)
    if not device:
        return False
    r = await db.execute(
        select(Arinc429Label).where(
            Arinc429Label.id == label_pk,
            Arinc429Label.device_id == device.id,
        )
    )
    row = r.scalar_one_or_none()
    if not row:
        return False
    await db.execute(delete(Arinc429Label).where(Arinc429Label.id == label_pk))
    await db.commit()
    return True


async def list_protocol_versions(
    db: AsyncSession,
    device_id: str,
) -> List[Dict[str, Any]]:
    device = await get_device_by_key(db, device_id)
    if not device:
        raise ValueError("设备不存在")
    r = await db.execute(
        select(Arinc429DeviceProtocolVersion)
        .where(Arinc429DeviceProtocolVersion.device_id == device.id)
        .order_by(Arinc429DeviceProtocolVersion.id)
    )
    rows = list(r.scalars().all())
    return [{"id": x.id, "version_name": x.version_name, "version": x.version} for x in rows]


async def list_version_history(
    db: AsyncSession,
    device_id: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    device = await get_device_by_key(db, device_id)
    if not device:
        raise ValueError("设备不存在")
    r = await db.execute(
        select(Arinc429VersionHistory)
        .where(Arinc429VersionHistory.device_id == device.id)
        .order_by(Arinc429VersionHistory.updated_at.desc())
        .limit(limit)
    )
    rows = list(r.scalars().all())
    out = []
    for h in rows:
        out.append(
            {
                "version": h.version,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "updated_by": h.updated_by,
                "change_summary": h.change_summary,
                "diff_summary": h.diff_summary,
                "label_count": h.label_count,
            }
        )
    return out


async def get_snapshot_labels(
    db: AsyncSession,
    device_id: str,
    history_version: str,
) -> List[Dict[str, Any]]:
    device = await get_device_by_key(db, device_id)
    if not device:
        raise ValueError("设备不存在")
    r = await db.execute(
        select(Arinc429VersionHistory)
        .where(
            Arinc429VersionHistory.device_id == device.id,
            Arinc429VersionHistory.version == history_version,
        )
        .order_by(Arinc429VersionHistory.updated_at.desc())
        .limit(1)
    )
    h = r.scalar_one_or_none()
    if not h or not h.label_snapshot:
        return []
    snap = h.label_snapshot
    if isinstance(snap, list):
        return snap
    return []


async def restore_from_history(
    db: AsyncSession,
    device_id: str,
    history_version: str,
    *,
    updated_by: Optional[str] = None,
) -> int:
    snap = await get_snapshot_labels(db, device_id, history_version)
    if not snap:
        raise ValueError("未找到该历史版本快照")
    # 去掉 id 字段再保存
    clean = []
    for item in snap:
        if isinstance(item, dict):
            c = {k: v for k, v in item.items() if k != "id"}
            clean.append(c)
    n, _ = await save_labels(
        db,
        device_id,
        clean,
        protocol_version_id=None,
        updated_by=updated_by,
        change_summary=f"从历史版本 {history_version} 恢复",
        bump_version=False,
    )
    return n
