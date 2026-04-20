# -*- coding: utf-8 -*-
"""站内通知路由（MR2）"""
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Notification, User


router = APIRouter(prefix="/api/notifications", tags=["站内通知"])


def _serialize(n: Notification) -> Dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "read_at": n.read_at,
        "created_at": n.created_at,
    }


@router.get("")
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = (
        select(Notification)
        .where(Notification.username == user.username)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    res = await db.execute(stmt)
    items = list(res.scalars().all())

    unread_res = await db.execute(
        select(func.count(Notification.id))
        .where(Notification.username == user.username)
        .where(Notification.read_at.is_(None))
    )
    unread_count = int(unread_res.scalar() or 0)
    return {
        "total": len(items),
        "unread_count": unread_count,
        "items": [_serialize(n) for n in items],
    }


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    res = await db.execute(
        select(Notification)
        .where(Notification.id == notif_id)
        .where(Notification.username == user.username)
    )
    notif = res.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="通知不存在")
    if notif.read_at is None:
        notif.read_at = datetime.utcnow()
        await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await db.execute(
        update(Notification)
        .where(Notification.username == user.username)
        .where(Notification.read_at.is_(None))
        .values(read_at=datetime.utcnow())
    )
    await db.commit()
    return {"status": "ok"}
