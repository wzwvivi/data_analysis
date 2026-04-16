# -*- coding: utf-8 -*-
"""登录与当前用户"""
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS
from ..database import get_db
from ..deps import get_current_user, require_admin, get_visible_ports, list_all_ports_for_protocol
from ..models import User, ParseTask
from ..permissions import ROLE_ADMIN, ROLE_KEYS, ROLE_META_LIST, get_role_pages, is_valid_role
from ..services.auth_password import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip()


class UserBrief(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    role: str

    class Config:
        from_attributes = True


class UserAdminBrief(UserBrief):
    created_at: Optional[datetime] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserBrief


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = "user"

    @field_validator("username")
    @classmethod
    def strip_username(cls, v: str) -> str:
        return v.strip()

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = (v or "").strip()
        if not is_valid_role(role):
            raise ValueError("不支持的角色")
        return role


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class UserRoleUpdateRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=20)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = (v or "").strip()
        if not is_valid_role(role):
            raise ValueError("不支持的角色")
        return role


class PermissionResponse(BaseModel):
    role: str
    pages: list[str]
    visible_ports: dict[str, list[int]]


class LegacyUserSummaryResponse(BaseModel):
    total: int
    users: list[UserAdminBrief]


def _create_token(username: str, role: str) -> str:
    exp = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": exp},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(User).where(User.username == body.username))
    user = r.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    token = _create_token(user.username, user.role or "user")
    return LoginResponse(
        access_token=token,
        user=UserBrief(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role or "user",
        ),
    )


@router.get("/me", response_model=UserBrief)
async def me(user: User = Depends(get_current_user)):
    return UserBrief(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role or "user",
    )


@router.get("/users", response_model=list[UserAdminBrief])
async def list_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).order_by(User.created_at.desc(), User.id.desc()))
    users = r.scalars().all()
    return [
        UserAdminBrief(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role or "user",
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users", response_model=UserBrief)
async def create_user(
    body: CreateUserRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.username == body.username))
    exists = r.scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=body.username,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserBrief(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role or "user",
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")

    r = await db.execute(select(User).where(User.id == user_id))
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    if (target.role or "user") == ROLE_ADMIN:
        cnt_r = await db.execute(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        admin_count = int(cnt_r.scalar_one() or 0)
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个管理员")

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return {"ok": True, "id": user_id}


@router.put("/password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    body: ResetPasswordRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.id == user_id))
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="请使用个人修改密码接口修改当前账号密码")

    target.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/role", response_model=UserBrief)
async def update_user_role(
    user_id: int,
    body: UserRoleUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能修改当前登录账号角色")

    r = await db.execute(select(User).where(User.id == user_id))
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")

    current_role = (target.role or "").strip()
    if current_role == ROLE_ADMIN and body.role != ROLE_ADMIN:
        cnt_r = await db.execute(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        admin_count = int(cnt_r.scalar_one() or 0)
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能降级最后一个管理员")

    target.role = body.role
    await db.commit()
    await db.refresh(target)
    return UserBrief(
        id=target.id,
        username=target.username,
        display_name=target.display_name,
        role=target.role or "user",
    )


@router.get("/roles")
async def list_roles(_: User = Depends(require_admin)):
    return {
        "roles": [{"key": r.key, "name": r.name, "description": r.description} for r in ROLE_META_LIST],
        "role_keys": ROLE_KEYS,
    }


@router.get("/permissions", response_model=PermissionResponse)
async def my_permissions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    role = (user.role or "user").strip()
    pages = get_role_pages(role)

    protocol_versions = await db.execute(
        select(ParseTask.protocol_version_id)
        .where(ParseTask.protocol_version_id.is_not(None))
        .distinct()
    )
    visible_ports: dict[str, list[int]] = {}
    for version_id in protocol_versions.scalars().all():
        all_ports = await list_all_ports_for_protocol(db, version_id)
        if role == ROLE_ADMIN:
            visible_ports[str(version_id)] = all_ports
            continue
        allowed = await get_visible_ports(
            db,
            role=role,
            protocol_version_id=version_id,
        )
        allowed = allowed or set()
        visible_ports[str(version_id)] = sorted([p for p in all_ports if p in allowed])

    return PermissionResponse(role=role, pages=pages, visible_ports=visible_ports)


@router.get("/users/legacy-role", response_model=LegacyUserSummaryResponse)
async def list_legacy_role_users(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出历史 user 角色账号，便于管理员逐个迁移到精细化角色。"""
    r = await db.execute(
        select(User)
        .where(User.role == "user")
        .order_by(User.created_at.desc(), User.id.desc())
    )
    rows = r.scalars().all()
    users = [
        UserAdminBrief(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role or "user",
            created_at=u.created_at,
        )
        for u in rows
    ]
    return LegacyUserSummaryResponse(total=len(users), users=users)
