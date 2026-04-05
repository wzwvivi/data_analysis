# -*- coding: utf-8 -*-
"""登录与当前用户"""
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services.auth_password import verify_password

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
    role: str

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserBrief


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
        user=UserBrief(id=user.id, username=user.username, role=user.role or "user"),
    )


@router.get("/me", response_model=UserBrief)
async def me(user: User = Depends(get_current_user)):
    return UserBrief(id=user.id, username=user.username, role=user.role or "user")
