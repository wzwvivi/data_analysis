# -*- coding: utf-8 -*-
"""站内通知服务（MR2 最小闭环）

- 只做站内消息表 + 未读计数。邮件/IM 不做。
- 以 username 为主要索引（避免新建账号时 user_id 不稳定）。
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification, User


async def notify_user(
    db: AsyncSession,
    *,
    username: str,
    kind: str,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Notification:
    n = Notification(
        user_id=user_id,
        username=username,
        kind=kind,
        title=title,
        body=body,
        link=link,
    )
    db.add(n)
    await db.flush()
    return n


async def notify_users_by_role(
    db: AsyncSession,
    *,
    role: str,
    kind: str,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
) -> List[Notification]:
    res = await db.execute(select(User).where(User.role == role))
    users = list(res.scalars().all())
    created: List[Notification] = []
    for u in users:
        created.append(
            await notify_user(
                db,
                username=u.username,
                user_id=u.id,
                kind=kind,
                title=title,
                body=body,
                link=link,
            )
        )
    return created


async def notify_usernames(
    db: AsyncSession,
    *,
    usernames: Iterable[str],
    kind: str,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
) -> List[Notification]:
    created: List[Notification] = []
    seen = set()
    for name in usernames:
        if not name or name in seen:
            continue
        seen.add(name)
        # 顺便尝试查 user_id，失败则留空
        res = await db.execute(select(User).where(User.username == name))
        u = res.scalar_one_or_none()
        created.append(
            await notify_user(
                db,
                username=name,
                user_id=u.id if u else None,
                kind=kind,
                title=title,
                body=body,
                link=link,
            )
        )
    return created
