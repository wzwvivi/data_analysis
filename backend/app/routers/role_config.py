# -*- coding: utf-8 -*-
"""角色配置路由（管理员）"""
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_admin, list_all_ports_for_protocol
from ..models import RolePortAccess, User
from ..permissions import ROLE_ADMIN, ROLE_KEYS, ROLE_META_LIST, is_valid_role

router = APIRouter(prefix="/api/role-config", tags=["角色配置"])


class RolePortSetRequest(BaseModel):
    protocol_version_id: int = Field(..., ge=1)
    ports: list[int] = Field(default_factory=list)

    @field_validator("ports")
    @classmethod
    def normalize_ports(cls, ports: list[int]) -> list[int]:
        normalized = sorted({int(p) for p in ports if int(p) > 0})
        return normalized


@router.get("/roles")
async def get_roles(_: User = Depends(require_admin)):
    return {
        "roles": [{"key": r.key, "name": r.name, "description": r.description} for r in ROLE_META_LIST]
    }


@router.get("/{role}/ports")
async def get_role_ports(
    role: str,
    protocol_version_id: int = Query(..., ge=1),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_role(role):
        raise HTTPException(status_code=400, detail="无效角色")
    if role == ROLE_ADMIN:
        all_ports = await list_all_ports_for_protocol(db, protocol_version_id)
        return {
            "role": role,
            "protocol_version_id": protocol_version_id,
            "ports": all_ports,
            "all_ports": all_ports,
            "admin_unrestricted": True,
        }

    all_ports = await list_all_ports_for_protocol(db, protocol_version_id)
    rows = await db.execute(
        select(RolePortAccess.port_number).where(
            RolePortAccess.role == role,
            RolePortAccess.protocol_version_id == protocol_version_id,
        )
    )
    ports = sorted({int(p) for p in rows.scalars().all()})
    return {
        "role": role,
        "protocol_version_id": protocol_version_id,
        "ports": ports,
        "all_ports": all_ports,
        "admin_unrestricted": False,
    }


@router.put("/{role}/ports")
async def set_role_ports(
    role: str,
    body: RolePortSetRequest,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not is_valid_role(role):
        raise HTTPException(status_code=400, detail="无效角色")
    if role == ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="管理员角色不需要配置端口权限")

    all_ports = set(await list_all_ports_for_protocol(db, body.protocol_version_id))
    invalid_ports = [p for p in body.ports if p not in all_ports]
    if invalid_ports:
        raise HTTPException(status_code=400, detail=f"存在无效端口: {invalid_ports}")

    await db.execute(
        delete(RolePortAccess).where(
            RolePortAccess.role == role,
            RolePortAccess.protocol_version_id == body.protocol_version_id,
        )
    )
    for p in body.ports:
        db.add(
            RolePortAccess(
                role=role,
                protocol_version_id=body.protocol_version_id,
                port_number=p,
            )
        )
    await db.commit()

    return {
        "ok": True,
        "role": role,
        "protocol_version_id": body.protocol_version_id,
        "ports": body.ports,
    }
