# -*- coding: utf-8 -*-
"""协议库路由

本模块是「用户选版本」那一侧的只读入口：解析任务、事件分析页都通过
`GET /api/protocols/versions` 拿候选版本。按 `ProtocolVersion.availability_status`
过滤，默认仅暴露 `Available`，让 `PendingCode / Deprecated` 状态的版本对终端用户
完全不可见。网络团队自己的 **TSN 网络配置管理**工作台（草稿 / 审批 / 激活）走 `/api/network-config`，
不跟这里混用。
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..deps import get_current_user
from ..models import (
    Protocol,
    ProtocolVersion,
    PortDefinition,
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_DEPRECATED,
)
from ..services import ProtocolService
from ..schemas import (
    ProtocolCreate, ProtocolResponse, ProtocolListResponse,
    ProtocolVersionResponse,
)

router = APIRouter(
    prefix="/api/protocols",
    tags=["协议库"],
    dependencies=[Depends(get_current_user)],
)


async def _fetch_user_visible_versions(
    db: AsyncSession,
    *,
    include_deprecated: bool = False,
) -> List[ProtocolVersion]:
    """取所有用户可选的协议版本（默认仅 Available）。"""
    allowed = [AVAILABILITY_AVAILABLE]
    if include_deprecated:
        allowed.append(AVAILABILITY_DEPRECATED)
    result = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.availability_status.in_(allowed))
        .options(
            selectinload(ProtocolVersion.protocol),
            selectinload(ProtocolVersion.ports),
        )
        .order_by(ProtocolVersion.created_at.desc())
    )
    return list(result.scalars().all())


async def _ensure_version_user_visible(
    db: AsyncSession,
    version_id: int,
) -> ProtocolVersion:
    """对端口/字段等下钻接口做可见性收口；`PendingCode / Deprecated` 版本对用户不可选。"""
    result = await db.execute(
        select(ProtocolVersion).where(ProtocolVersion.id == version_id)
    )
    pv = result.scalar_one_or_none()
    if pv is None:
        raise HTTPException(status_code=404, detail="TSN 网络协议版本不存在")
    if pv.availability_status != AVAILABILITY_AVAILABLE:
        raise HTTPException(status_code=404, detail="该 TSN 网络协议版本当前不可用")
    return pv


@router.get("", response_model=ProtocolListResponse)
async def list_protocols(db: AsyncSession = Depends(get_db)):
    """协议列表（按 Available 过滤嵌套版本）"""
    result = await db.execute(
        select(Protocol).options(
            selectinload(Protocol.versions).selectinload(ProtocolVersion.ports)
        ).order_by(Protocol.id.asc())
    )
    protocols = result.scalars().all()

    items: List[ProtocolResponse] = []
    for p in protocols:
        versions = [
            ProtocolVersionResponse(
                id=v.id,
                version=v.version,
                source_file=v.source_file,
                description=v.description,
                created_at=v.created_at,
                port_count=len(v.ports) if v.ports else 0,
            )
            for v in (p.versions or [])
            if getattr(v, "availability_status", AVAILABILITY_AVAILABLE) == AVAILABILITY_AVAILABLE
        ]
        if not versions:
            # 协议下全是 PendingCode / Deprecated，对用户列表也不暴露
            continue
        items.append(
            ProtocolResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                created_at=p.created_at,
                updated_at=p.updated_at,
                versions=versions,
            )
        )
    return ProtocolListResponse(total=len(items), items=items)


@router.post("", response_model=ProtocolResponse)
async def create_protocol(
    _data: ProtocolCreate,
    _db: AsyncSession = Depends(get_db),
):
    """创建协议（禁用：请走「TSN 网络配置管理」/ `/api/network-config` 审批发布流程）"""
    raise HTTPException(
        status_code=403,
        detail="请通过 TSN 网络配置管理（网络团队；审批 → 发布 → 激活）创建新版本",
    )


@router.post("/import")
async def import_icd(_db: AsyncSession = Depends(get_db)):
    """导入 ICD Excel（禁用：请走审批流程）"""
    raise HTTPException(
        status_code=403,
        detail="请通过网络团队配置管理（审批 → 发布 → 激活）导入新版本",
    )


@router.get("/versions")
async def list_all_versions(db: AsyncSession = Depends(get_db)):
    """所有可选协议版本扁平列表（供上传/事件分析页选版本下拉）"""
    versions = await _fetch_user_visible_versions(db)
    return {
        "total": len(versions),
        "items": [
            {
                "id": v.id,
                "protocol_id": v.protocol_id,
                "protocol_name": v.protocol.name if v.protocol else None,
                "version": v.version,
                "source_file": v.source_file,
                "description": v.description,
                "created_at": v.created_at,
                "availability_status": v.availability_status,
                "port_count": len(v.ports) if v.ports else 0,
            }
            for v in versions
        ],
    }


@router.get("/versions/{version_id}/ports")
async def get_version_ports(version_id: int, db: AsyncSession = Depends(get_db)):
    """版本下端口定义（仅 Available 版本可下钻）"""
    await _ensure_version_user_visible(db, version_id)
    service = ProtocolService(db)
    ports = await service.get_ports_by_version(version_id)

    return {
        "total": len(ports),
        "items": [
            {
                "id": p.id,
                "port_number": p.port_number,
                "message_name": p.message_name,
                "source_device": p.source_device,
                "target_device": p.target_device,
                "multicast_ip": p.multicast_ip,
                "data_direction": p.data_direction,
                "period_ms": p.period_ms,
                "protocol_family": p.protocol_family,
                "field_count": len(p.fields) if p.fields else 0,
            }
            for p in ports
        ],
    }


@router.get("/versions/{version_id}/devices")
async def get_version_devices(version_id: int, db: AsyncSession = Depends(get_db)):
    """版本下设备聚合列表（仅 Available 版本可下钻）"""
    await _ensure_version_user_visible(db, version_id)
    service = ProtocolService(db)
    devices = await service.get_devices_with_family(version_id)
    return {
        "version_id": version_id,
        "total": len(devices),
        "items": devices,
    }


@router.get("/versions/{version_id}/ports/{port_number}")
async def get_port_detail(
    version_id: int,
    port_number: int,
    db: AsyncSession = Depends(get_db),
):
    """端口详情（含字段定义；仅 Available 版本可下钻）"""
    await _ensure_version_user_visible(db, version_id)
    service = ProtocolService(db)
    port = await service.get_port_by_number(version_id, port_number)
    if not port:
        raise HTTPException(status_code=404, detail="端口定义不存在")

    return {
        "id": port.id,
        "port_number": port.port_number,
        "message_name": port.message_name,
        "source_device": port.source_device,
        "target_device": port.target_device,
        "multicast_ip": port.multicast_ip,
        "data_direction": port.data_direction,
        "period_ms": port.period_ms,
        "protocol_family": port.protocol_family,
        "fields": [
            {
                "id": f.id,
                "field_name": f.field_name,
                "field_offset": f.field_offset,
                "field_length": f.field_length,
                "data_type": f.data_type,
                "scale_factor": f.scale_factor,
                "unit": f.unit,
                "description": f.description,
                "byte_order": f.byte_order,
            }
            for f in port.fields
        ],
    }


# ========== 动态路径路由放在最后 ==========


@router.get("/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(protocol_id: int, db: AsyncSession = Depends(get_db)):
    """协议详情（只返回 Available 版本）"""
    service = ProtocolService(db)
    protocol = await service.get_protocol(protocol_id)
    if not protocol:
        raise HTTPException(status_code=404, detail="协议不存在")

    versions = [
        ProtocolVersionResponse(
            id=v.id,
            version=v.version,
            source_file=v.source_file,
            description=v.description,
            created_at=v.created_at,
            port_count=len(v.ports) if hasattr(v, "ports") and v.ports else 0,
        )
        for v in protocol.versions
        if getattr(v, "availability_status", AVAILABILITY_AVAILABLE) == AVAILABILITY_AVAILABLE
    ]

    return ProtocolResponse(
        id=protocol.id,
        name=protocol.name,
        description=protocol.description,
        created_at=protocol.created_at,
        updated_at=protocol.updated_at,
        versions=versions,
    )
