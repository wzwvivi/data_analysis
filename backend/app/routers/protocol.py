# -*- coding: utf-8 -*-
"""协议库路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services import ProtocolService
from ..schemas import (
    ProtocolCreate, ProtocolResponse, ProtocolListResponse,
    ProtocolVersionResponse, PortDefinitionResponse
)

router = APIRouter(prefix="/api/protocols", tags=["协议库"])
FIXED_PROTOCOL_NAME = "TSN ICD"
FIXED_PROTOCOL_VERSION = "v6.0.1"


async def _get_fixed_visible_version(service: ProtocolService):
    """从现有配置中选出唯一可见版本，并映射为固定名称/版本号"""
    protocols = await service.get_protocols()

    candidates = []
    for p in protocols:
        for v in p.versions:
            candidates.append((p, v))

    if not candidates:
        return None

    # 优先保留包含 tsn2.0 的版本；若不存在则按端口数量和创建时间选择最优候选
    preferred = [
        (p, v) for p, v in candidates
        if "tsn2.0" in (p.name or "").lower() or "tsn2.0" in (v.version or "").lower()
    ]
    pool = preferred if preferred else candidates
    pool.sort(
        key=lambda pv: (
            len(pv[1].ports) if hasattr(pv[1], "ports") and pv[1].ports else 0,
            pv[1].created_at,
        ),
        reverse=True,
    )
    protocol, version = pool[0]
    return {
        "protocol": protocol,
        "version": version,
        "protocol_name": FIXED_PROTOCOL_NAME,
        "version_name": FIXED_PROTOCOL_VERSION,
    }


@router.get("", response_model=ProtocolListResponse)
async def list_protocols(db: AsyncSession = Depends(get_db)):
    """获取协议列表（固定为单一 TSN ICD 版本）"""
    service = ProtocolService(db)
    picked = await _get_fixed_visible_version(service)
    if not picked:
        return ProtocolListResponse(total=0, items=[])

    p = picked["protocol"]
    v = picked["version"]
    item = ProtocolResponse(
        id=p.id,
        name=picked["protocol_name"],
        description=p.description,
        created_at=p.created_at,
        updated_at=p.updated_at,
        versions=[
            ProtocolVersionResponse(
                id=v.id,
                version=picked["version_name"],
                source_file=v.source_file,
                description=v.description,
                created_at=v.created_at,
                port_count=len(v.ports) if hasattr(v, "ports") else 0,
            )
        ],
    )
    return ProtocolListResponse(total=1, items=[item])


@router.post("", response_model=ProtocolResponse)
async def create_protocol(
    _data: ProtocolCreate,
    _db: AsyncSession = Depends(get_db)
):
    """创建协议（已禁用）"""
    raise HTTPException(status_code=403, detail="网络配置为内置固定版本，不允许新增")


# ========== 固定路径路由必须在 /{protocol_id} 之前 ==========

@router.post("/import")
async def import_icd(
    _db: AsyncSession = Depends(get_db),
):
    """导入ICD Excel文件（已禁用）"""
    raise HTTPException(status_code=403, detail="网络配置上传已禁用，仅保留内置 TSN ICD v6.0.1")


@router.get("/versions")
async def list_all_versions(db: AsyncSession = Depends(get_db)):
    """获取所有网络配置版本（固定为单一 TSN ICD 版本）"""
    service = ProtocolService(db)
    picked = await _get_fixed_visible_version(service)
    if not picked:
        return {"total": 0, "items": []}

    p = picked["protocol"]
    v = picked["version"]
    return {
        "total": 1,
        "items": [{
            "id": v.id,
            "protocol_id": p.id,
            "protocol_name": picked["protocol_name"],
            "version": picked["version_name"],
            "source_file": v.source_file,
            "description": v.description,
            "created_at": v.created_at,
            "port_count": len(v.ports) if hasattr(v, "ports") else 0,
        }],
    }


@router.get("/versions/{version_id}/ports")
async def get_version_ports(version_id: int, db: AsyncSession = Depends(get_db)):
    """获取版本下的端口定义"""
    service = ProtocolService(db)
    picked = await _get_fixed_visible_version(service)
    if not picked or version_id != picked["version"].id:
        raise HTTPException(status_code=404, detail="网络配置版本不存在")
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
                "field_count": len(p.fields) if p.fields else 0
            }
            for p in ports
        ]
    }


@router.get("/versions/{version_id}/devices")
async def get_version_devices(version_id: int, db: AsyncSession = Depends(get_db)):
    """获取版本下的设备列表（含协议族和可选解析器版本）
    
    返回设备列表，每个设备包含:
    - device_name: 设备名称
    - ports: 端口号列表
    - messages: 消息名称列表
    - port_count: 端口数量
    - direction: 数据方向(source/target/both)
    - protocol_family: 协议族标识
    - available_parsers: 该协议族下可选的解析器版本列表
    """
    service = ProtocolService(db)
    picked = await _get_fixed_visible_version(service)
    if not picked or version_id != picked["version"].id:
        raise HTTPException(status_code=404, detail="网络配置版本不存在")
    
    version = await service.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="网络配置版本不存在")
    
    devices = await service.get_devices_with_family(version_id)
    
    return {
        "version_id": version_id,
        "total": len(devices),
        "items": devices
    }


@router.get("/versions/{version_id}/ports/{port_number}")
async def get_port_detail(
    version_id: int, 
    port_number: int, 
    db: AsyncSession = Depends(get_db)
):
    """获取端口详情（包含字段定义）"""
    service = ProtocolService(db)
    picked = await _get_fixed_visible_version(service)
    if not picked or version_id != picked["version"].id:
        raise HTTPException(status_code=404, detail="网络配置版本不存在")
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
                "byte_order": f.byte_order
            }
            for f in port.fields
        ]
    }


# ========== 动态路径路由放在最后 ==========

@router.get("/{protocol_id}", response_model=ProtocolResponse)
async def get_protocol(protocol_id: int, db: AsyncSession = Depends(get_db)):
    """获取协议详情"""
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
            port_count=len(v.ports) if hasattr(v, 'ports') else 0
        )
        for v in protocol.versions
    ]
    
    return ProtocolResponse(
        id=protocol.id,
        name=protocol.name,
        description=protocol.description,
        created_at=protocol.created_at,
        updated_at=protocol.updated_at,
        versions=versions
    )
