# -*- coding: utf-8 -*-
"""平台共享 TSN 数据（管理员上传，全员可选用）"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import User, SharedTsnFile
from ..services import shared_tsn_service as sts

router = APIRouter(prefix="/api/shared-tsn", tags=["平台共享TSN"])


class SharedTsnResponse(BaseModel):
    id: int
    original_filename: str
    experiment_date: Optional[str] = None
    experiment_label: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class SharedTsnUpdate(BaseModel):
    experiment_date: Optional[date] = None
    experiment_label: Optional[str] = Field(None, max_length=500)


def _to_resp(row: SharedTsnFile) -> SharedTsnResponse:
    return SharedTsnResponse(
        id=row.id,
        original_filename=row.original_filename,
        experiment_date=row.experiment_date.isoformat() if row.experiment_date else None,
        experiment_label=row.experiment_label,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get("", response_model=List[SharedTsnResponse])
async def list_shared(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = await sts.list_shared_files(db)
    return [_to_resp(r) for r in rows]


@router.post("/upload")
async def upload_shared(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    raw = file.filename or "capture.pcapng"
    data = await file.read()
    try:
        await sts.purge_expired_shared_files(db)
        row = await sts.create_shared_from_upload(
            db, filename=raw, file_bytes=data, uploaded_by_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "id": row.id, "message": "已上传至平台共享库"}


@router.patch("/{shared_id}", response_model=SharedTsnResponse)
async def update_shared(
    shared_id: int,
    body: SharedTsnUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    row = await sts.update_shared_meta(
        db,
        row,
        experiment_date=patch.get("experiment_date"),
        experiment_label=patch.get("experiment_label"),
        patch_keys=set(patch.keys()),
    )
    return _to_resp(row)


@router.delete("/{shared_id}")
async def delete_shared(
    shared_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    await sts.delete_shared(db, row)
    return {"success": True}
