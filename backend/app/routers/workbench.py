# -*- coding: utf-8 -*-
"""试验工作台：按架次汇总元数据（视频/网络数据等由前端继续调 shared-tsn、parse）。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..deps import get_current_user
from ..models import User, SharedSortie, SharedTsnFile
from ..services import shared_tsn_service as sts

router = APIRouter(prefix="/api/workbench", tags=["试验工作台"])


class WbFileItem(BaseModel):
    id: int
    original_filename: str
    asset_type: Optional[str] = None
    asset_label: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class WbSortieDetail(BaseModel):
    id: int
    sortie_label: str
    experiment_date: Optional[str] = None
    remarks: Optional[str] = None
    created_at: Optional[str] = None
    files: List[WbFileItem] = []


@router.get("/sorties/{sortie_id}", response_model=WbSortieDetail)
async def get_sortie_for_workbench(
    sortie_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """单次试验（架次）详情，供工作台页加载。"""
    r = await db.execute(
        select(SharedSortie)
        .options(selectinload(SharedSortie.files))
        .where(SharedSortie.id == sortie_id)
    )
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="试验架次不存在")
    files: List[WbFileItem] = []
    for f in sorted(s.files or [], key=lambda x: x.id, reverse=True):
        files.append(
            WbFileItem(
                id=f.id,
                original_filename=f.original_filename,
                asset_type=f.asset_type,
                asset_label=sts.asset_label_for_key(f.asset_type),
                created_at=f.created_at.isoformat() if f.created_at else None,
            )
        )
    return WbSortieDetail(
        id=s.id,
        sortie_label=s.sortie_label,
        experiment_date=s.experiment_date.isoformat() if s.experiment_date else None,
        remarks=s.remarks,
        created_at=s.created_at.isoformat() if s.created_at else None,
        files=files,
    )
