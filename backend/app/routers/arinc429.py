# -*- coding: utf-8 -*-
"""协议管理（设备树、Label、版本）— 写操作需管理员"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import User
from ..schemas.arinc429 import (
    Arinc429DeviceCreate,
    Arinc429DeviceTreeResponse,
    Arinc429LabelsSaveRequest,
    Arinc429ProtocolVersionResponse,
    Arinc429SystemCreate,
    Arinc429VersionHistoryItem,
)
from ..services import arinc429_service as ar_svc

router = APIRouter(prefix="/api/protocol-manager", tags=["协议管理"])


class ActiveVersionBody(BaseModel):
    current_version_name: str = Field(..., min_length=1, max_length=200)


@router.get("/device-tree", response_model=Arinc429DeviceTreeResponse)
async def get_device_tree(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items = await ar_svc.get_device_tree(db)
    return Arinc429DeviceTreeResponse(items=items)


@router.post("/systems")
async def create_system(
    body: Arinc429SystemCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        row = await ar_svc.create_system(
            db,
            name=body.name,
            parent_id=body.parent_id,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "id": row.id, "device_id": row.device_id}


@router.post("/devices")
async def create_device(
    body: Arinc429DeviceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        row = await ar_svc.create_leaf_device(
            db,
            name=body.name,
            parent_id=body.parent_id,
            device_id=body.device_id,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "id": row.id, "device_id": row.device_id}


@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ok = await ar_svc.delete_device_by_key(db, device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="设备不存在")
    return {"success": True}


@router.put("/devices/{device_id}/active-version")
async def set_active_version(
    device_id: str,
    body: ActiveVersionBody,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    d = await ar_svc.get_device_by_key(db, device_id)
    if not d or not d.is_device:
        raise HTTPException(status_code=404, detail="设备不存在")
    from sqlalchemy import select

    from ..models import Arinc429DeviceProtocolVersion

    r = await db.execute(
        select(Arinc429DeviceProtocolVersion).where(
            Arinc429DeviceProtocolVersion.device_id == d.id,
            Arinc429DeviceProtocolVersion.version_name == body.current_version_name,
        )
    )
    pv = r.scalar_one_or_none()
    if not pv:
        raise HTTPException(status_code=400, detail="协议版本不存在")
    from datetime import datetime as dt

    d.current_version_name = body.current_version_name
    d.updated_at = dt.utcnow()
    await db.commit()
    return {"success": True}


@router.get("/devices/{device_id}/labels")
async def get_labels(
    device_id: str,
    protocol_version_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        items = await ar_svc.list_labels(db, device_id, protocol_version_id=protocol_version_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"items": items}


@router.post("/devices/{device_id}/labels")
async def save_labels(
    device_id: str,
    body: Arinc429LabelsSaveRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        n, new_ver = await ar_svc.save_labels(
            db,
            device_id,
            body.labels,
            protocol_version_id=body.protocol_version_id,
            updated_by=admin.username,
            change_summary=body.change_summary,
            bump_version=body.bump_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "count": n, "new_version": new_ver}


@router.delete("/devices/{device_id}/labels/{label_id}")
async def delete_label(
    device_id: str,
    label_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ok = await ar_svc.delete_label(db, device_id, label_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Label 不存在")
    return {"success": True}


@router.get("/devices/{device_id}/versions", response_model=List[Arinc429ProtocolVersionResponse])
async def list_versions(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        items = await ar_svc.list_protocol_versions(db, device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return items


@router.get("/devices/{device_id}/history", response_model=List[Arinc429VersionHistoryItem])
async def list_history(
    device_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        items = await ar_svc.list_version_history(db, device_id, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return items


@router.get("/devices/{device_id}/versions/{version}/labels")
async def get_version_snapshot_labels(
    device_id: str,
    version: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        items = await ar_svc.get_snapshot_labels(db, device_id, version)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"items": items}


@router.post("/devices/{device_id}/versions/{version}/restore")
async def restore_version(
    device_id: str,
    version: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        n = await ar_svc.restore_from_history(
            db, device_id, version, updated_by=admin.username
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "count": n}
