# -*- coding: utf-8 -*-
"""认证依赖"""
from typing import Optional, Callable

import jwt
from fastapi import Depends, HTTPException, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import JWT_SECRET, JWT_ALGORITHM
from .database import get_db
from .models import User, RolePortAccess, PortDefinition
from .permissions import ROLE_ADMIN


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="未登录或令牌无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="无效令牌")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="无效或过期令牌")

    r = await db.execute(select(User).where(User.username == sub))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if (user.role or "").lower() != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_roles(*allowed_roles: str) -> Callable:
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        role = (user.role or "").strip()
        if role == ROLE_ADMIN:
            return user
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="无权访问")
        return user

    return Depends(_dependency)


async def get_visible_ports(
    db: AsyncSession,
    *,
    role: str,
    protocol_version_id: Optional[int],
) -> Optional[set[int]]:
    """返回角色在某协议版本下可见端口集合。

    返回 None 表示不限制（管理员或无协议版本上下文）。
    """
    normalized = (role or "").strip()
    if normalized == ROLE_ADMIN or protocol_version_id is None:
        return None

    allowed_q = await db.execute(
        select(RolePortAccess.port_number).where(
            RolePortAccess.role == normalized,
            RolePortAccess.protocol_version_id == protocol_version_id,
        )
    )
    configured = {int(p) for p in allowed_q.scalars().all()}
    if configured:
        return configured

    # 角色未配置时默认无权限（安全默认值）
    return set()


async def ensure_port_visible_or_403(
    db: AsyncSession,
    *,
    user: User,
    protocol_version_id: Optional[int],
    port_number: int,
) -> None:
    visible = await get_visible_ports(
        db,
        role=user.role or "",
        protocol_version_id=protocol_version_id,
    )
    if visible is None:
        return
    if int(port_number) not in visible:
        raise HTTPException(status_code=403, detail="当前角色无权访问该端口数据")


async def list_all_ports_for_protocol(
    db: AsyncSession, protocol_version_id: Optional[int]
) -> list[int]:
    if protocol_version_id is None:
        return []
    rows = await db.execute(
        select(PortDefinition.port_number).where(PortDefinition.protocol_version_id == protocol_version_id)
    )
    return sorted({int(p) for p in rows.scalars().all()})
