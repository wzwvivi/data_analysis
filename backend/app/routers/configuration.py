# -*- coding: utf-8 -*-
"""构型管理路由

提供：
  - /api/configurations/devices            设备库
  - /api/configurations/aircraft           飞机构型（TSN 协议 × 设备协议版本）
  - /api/configurations/software           软件构型
  - /api/configurations/software/{id}/entries  构型条目（设备 × 软件版本号）
  - /api/configurations/software/import-excel  Excel 一键导入
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import (
    AircraftConfiguration,
    Device,
    DeviceProtocolSpec,
    DeviceProtocolVersion,
    Protocol,
    ProtocolVersion,
    SoftwareConfiguration,
    User,
)
from ..services import configuration_service as cfg_svc


router = APIRouter(prefix="/api/configurations", tags=["构型管理"])


# ── 公共序列化器 ───────────────────────────────────────────────────────────
class DeviceOut(BaseModel):
    id: int
    team: str
    eata_chapter: Optional[str] = None
    device_cn_name: str
    device_dm_number: Optional[str] = None
    software_cn_name: str
    software_level: Optional[str] = None
    is_cds_resident: Optional[bool] = None
    is_field_loadable: Optional[bool] = None
    is_proprietary: Optional[bool] = None
    supplier: Optional[str] = None
    is_new_dev: Optional[bool] = None
    has_software: Optional[bool] = None
    remarks: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: Device) -> "DeviceOut":
        return cls(
            id=row.id,
            team=row.team,
            eata_chapter=row.eata_chapter,
            device_cn_name=row.device_cn_name,
            device_dm_number=row.device_dm_number,
            software_cn_name=row.software_cn_name,
            software_level=row.software_level,
            is_cds_resident=row.is_cds_resident,
            is_field_loadable=row.is_field_loadable,
            is_proprietary=row.is_proprietary,
            supplier=row.supplier,
            is_new_dev=row.is_new_dev,
            has_software=row.has_software,
            remarks=row.remarks,
            created_at=row.created_at.isoformat() if row.created_at else None,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )


class DeviceInput(BaseModel):
    team: str = Field(..., min_length=1, max_length=100)
    eata_chapter: Optional[str] = Field(None, max_length=200)
    device_cn_name: str = Field(..., min_length=1, max_length=200)
    device_dm_number: Optional[str] = Field(None, max_length=100)
    software_cn_name: str = Field(..., min_length=1, max_length=200)
    software_level: Optional[str] = Field(None, max_length=20)
    is_cds_resident: Optional[bool] = None
    is_field_loadable: Optional[bool] = None
    is_proprietary: Optional[bool] = None
    supplier: Optional[str] = Field(None, max_length=200)
    is_new_dev: Optional[bool] = None
    has_software: Optional[bool] = None
    remarks: Optional[str] = None


class AircraftConfigOut(BaseModel):
    id: int
    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    tsn_protocol_version_id: Optional[int] = None
    tsn_protocol_label: Optional[str] = None
    device_protocol_version_ids: List[int] = []
    device_protocol_summary: List[Dict[str, Any]] = []
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AircraftConfigInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    version: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    tsn_protocol_version_id: Optional[int] = None
    device_protocol_version_ids: List[int] = Field(default_factory=list)


class AircraftConfigPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    version: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    tsn_protocol_version_id: Optional[int] = None
    device_protocol_version_ids: Optional[List[int]] = None


class SoftwareConfigOut(BaseModel):
    id: int
    name: str
    snapshot_date: Optional[str] = None
    source: str
    source_file: Optional[str] = None
    description: Optional[str] = None
    entry_count: int = 0
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SoftwareConfigInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    snapshot_date: Optional[date] = None
    description: Optional[str] = None


class SoftwareConfigPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=300)
    snapshot_date: Optional[date] = None
    description: Optional[str] = None


class SoftwareEntryOut(BaseModel):
    id: int
    software_config_id: int
    device_id: int
    software_version_code: Optional[str] = None
    change_note: Optional[str] = None
    device: DeviceOut


class SoftwareEntriesPayload(BaseModel):
    items: List[Dict[str, Any]]
    replace_all: bool = False


# ── 辅助格式化 ────────────────────────────────────────────────────────────
async def _protocol_version_label_map(
    db: AsyncSession, pv_ids: List[int]
) -> Dict[int, str]:
    if not pv_ids:
        return {}
    r = await db.execute(
        select(ProtocolVersion, Protocol)
        .join(Protocol, Protocol.id == ProtocolVersion.protocol_id)
        .where(ProtocolVersion.id.in_(pv_ids))
    )
    out: Dict[int, str] = {}
    for pv, p in r.all():
        out[pv.id] = f"{p.name} / {pv.version}"
    return out


async def _device_protocol_summary(
    db: AsyncSession, dp_ids: List[int]
) -> List[Dict[str, Any]]:
    if not dp_ids:
        return []
    r = await db.execute(
        select(DeviceProtocolVersion, DeviceProtocolSpec)
        .join(DeviceProtocolSpec, DeviceProtocolSpec.id == DeviceProtocolVersion.spec_id)
        .where(DeviceProtocolVersion.id.in_(dp_ids))
    )
    items = []
    for v, spec in r.all():
        items.append(
            {
                "id": v.id,
                "version_name": v.version_name,
                "spec_id": spec.id,
                "device_id": spec.device_id,
                "device_name": spec.device_name,
                "protocol_family": spec.protocol_family,
                "ata_code": spec.ata_code,
            }
        )
    items.sort(key=lambda x: (x["protocol_family"] or "", x["device_name"] or "", x["version_name"] or ""))
    return items


async def _serialize_aircraft(
    db: AsyncSession, row: AircraftConfiguration
) -> AircraftConfigOut:
    dp_ids = [lnk.device_protocol_version_id for lnk in (row.device_protocol_links or [])]
    label_map = await _protocol_version_label_map(
        db, [row.tsn_protocol_version_id] if row.tsn_protocol_version_id else []
    )
    summary = await _device_protocol_summary(db, dp_ids)
    return AircraftConfigOut(
        id=row.id,
        name=row.name,
        version=row.version,
        description=row.description,
        tsn_protocol_version_id=row.tsn_protocol_version_id,
        tsn_protocol_label=label_map.get(row.tsn_protocol_version_id) if row.tsn_protocol_version_id else None,
        device_protocol_version_ids=dp_ids,
        device_protocol_summary=summary,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


async def _serialize_software(
    db: AsyncSession, row: SoftwareConfiguration
) -> SoftwareConfigOut:
    from sqlalchemy import func
    from ..models import SoftwareConfigurationEntry

    cnt_q = await db.execute(
        select(func.count(SoftwareConfigurationEntry.id)).where(
            SoftwareConfigurationEntry.software_config_id == row.id
        )
    )
    return SoftwareConfigOut(
        id=row.id,
        name=row.name,
        snapshot_date=row.snapshot_date.isoformat() if row.snapshot_date else None,
        source=row.source,
        source_file=row.source_file,
        description=row.description,
        entry_count=int(cnt_q.scalar() or 0),
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


# ═════════════════════════ 设备库 ═════════════════════════

@router.get("/devices", response_model=List[DeviceOut])
async def list_devices(
    team: Optional[str] = None,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = await cfg_svc.list_devices(db, team=team, keyword=q)
    return [DeviceOut.from_row(r) for r in rows]


@router.get("/devices/teams", response_model=List[str])
async def list_device_teams(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    r = await db.execute(select(Device.team).distinct())
    return sorted({x for x in r.scalars().all() if x})


@router.post("/devices", response_model=DeviceOut)
async def create_device(
    body: DeviceInput,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    try:
        row = await cfg_svc.create_device(db, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DeviceOut.from_row(row)


@router.put("/devices/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    body: DeviceInput,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_device_by_id(db, device_id)
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")
    try:
        row = await cfg_svc.update_device(db, row, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DeviceOut.from_row(row)


@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_device_by_id(db, device_id)
    if not row:
        raise HTTPException(status_code=404, detail="设备不存在")
    await cfg_svc.delete_device(db, row)
    return {"success": True}


# ═════════════════════════ 飞机构型 ═════════════════════════

@router.get("/aircraft", response_model=List[AircraftConfigOut])
async def list_aircraft_configs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = await cfg_svc.list_aircraft_configurations(db)
    return [await _serialize_aircraft(db, r) for r in rows]


@router.get("/aircraft/{cfg_id}", response_model=AircraftConfigOut)
async def get_aircraft_config(
    cfg_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await cfg_svc.get_aircraft_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="飞机构型不存在")
    return await _serialize_aircraft(db, row)


@router.post("/aircraft", response_model=AircraftConfigOut)
async def create_aircraft_config(
    body: AircraftConfigInput,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        row = await cfg_svc.create_aircraft_configuration(
            db,
            name=body.name,
            version=body.version,
            description=body.description,
            tsn_protocol_version_id=body.tsn_protocol_version_id,
            device_protocol_version_ids=body.device_protocol_version_ids,
            created_by=admin.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _serialize_aircraft(db, row)


@router.put("/aircraft/{cfg_id}", response_model=AircraftConfigOut)
async def update_aircraft_config(
    cfg_id: int,
    body: AircraftConfigPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_aircraft_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="飞机构型不存在")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    try:
        row = await cfg_svc.update_aircraft_configuration(
            db,
            row,
            name=patch.get("name"),
            version=patch.get("version"),
            description=patch.get("description"),
            tsn_protocol_version_id=patch.get("tsn_protocol_version_id"),
            device_protocol_version_ids=patch.get("device_protocol_version_ids"),
            patch_keys=set(patch.keys()),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _serialize_aircraft(db, row)


@router.delete("/aircraft/{cfg_id}")
async def delete_aircraft_config(
    cfg_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_aircraft_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="飞机构型不存在")
    await cfg_svc.delete_aircraft_configuration(db, row)
    return {"success": True}


# ═════════════════════════ 软件构型 ═════════════════════════

@router.get("/software", response_model=List[SoftwareConfigOut])
async def list_software_configs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = await cfg_svc.list_software_configurations(db)
    return [await _serialize_software(db, r) for r in rows]


@router.get("/software/{cfg_id}", response_model=SoftwareConfigOut)
async def get_software_config(
    cfg_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await cfg_svc.get_software_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="软件构型不存在")
    return await _serialize_software(db, row)


@router.post("/software", response_model=SoftwareConfigOut)
async def create_software_config(
    body: SoftwareConfigInput,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        row = await cfg_svc.create_software_configuration(
            db,
            name=body.name,
            snapshot_date=body.snapshot_date,
            description=body.description,
            created_by=admin.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _serialize_software(db, row)


@router.put("/software/{cfg_id}", response_model=SoftwareConfigOut)
async def update_software_config(
    cfg_id: int,
    body: SoftwareConfigPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_software_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="软件构型不存在")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    try:
        row = await cfg_svc.update_software_configuration(
            db,
            row,
            name=patch.get("name"),
            snapshot_date=patch.get("snapshot_date"),
            description=patch.get("description"),
            patch_keys=set(patch.keys()),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _serialize_software(db, row)


@router.delete("/software/{cfg_id}")
async def delete_software_config(
    cfg_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_software_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="软件构型不存在")
    await cfg_svc.delete_software_configuration(db, row)
    return {"success": True}


@router.get("/software/{cfg_id}/entries", response_model=List[SoftwareEntryOut])
async def list_software_entries(
    cfg_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await cfg_svc.get_software_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="软件构型不存在")
    rows = await cfg_svc.list_software_entries(db, cfg_id)
    return [
        SoftwareEntryOut(
            id=e.id,
            software_config_id=e.software_config_id,
            device_id=e.device_id,
            software_version_code=e.software_version_code,
            change_note=e.change_note,
            device=DeviceOut.from_row(d),
        )
        for e, d in rows
    ]


@router.put("/software/{cfg_id}/entries")
async def upsert_software_entries(
    cfg_id: int,
    body: SoftwareEntriesPayload,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await cfg_svc.get_software_configuration(db, cfg_id)
    if not row:
        raise HTTPException(status_code=404, detail="软件构型不存在")
    try:
        n = await cfg_svc.upsert_software_entries(
            db, row, body.items, replace_all=body.replace_all
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "updated": n}


@router.post("/software/import-excel")
async def import_software_excel(
    file: UploadFile = File(...),
    mode: str = Form("merge", description="merge | replace"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """上传《软件编号（...）.xlsx》，一次性 upsert 设备库与所有构型列。"""
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode 必须是 merge 或 replace")
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")
    data = await file.read()
    try:
        summary = await cfg_svc.import_excel_bytes(
            db,
            file_bytes=data,
            source_file=file.filename,
            created_by=admin.username,
            mode=mode,
        )
    except Exception as e:  # noqa: BLE001
        # openpyxl / 解析错误多为 ValueError；统一给前端一个可读消息
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{e}")
    return {"success": True, "summary": summary}


# ═════════════════════════ 选项（给前端下拉框用） ═════════════════════════

@router.get("/options/tsn-protocol-versions")
async def options_tsn_protocol_versions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """TSN 协议（ICD）所有版本 —— 便于飞机构型挑选。"""
    r = await db.execute(
        select(ProtocolVersion, Protocol)
        .join(Protocol, Protocol.id == ProtocolVersion.protocol_id)
        .order_by(Protocol.name, ProtocolVersion.created_at.desc())
    )
    out = []
    for pv, p in r.all():
        out.append(
            {
                "id": pv.id,
                "protocol_id": p.id,
                "protocol_name": p.name,
                "version": pv.version,
                "label": f"{p.name} / {pv.version}",
                "availability_status": pv.availability_status,
            }
        )
    return out


@router.get("/options/device-protocol-versions")
async def options_device_protocol_versions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """所有设备协议（ARINC429/CAN/RS422）版本 —— 便于飞机构型多选。"""
    r = await db.execute(
        select(DeviceProtocolVersion, DeviceProtocolSpec)
        .join(DeviceProtocolSpec, DeviceProtocolSpec.id == DeviceProtocolVersion.spec_id)
        .order_by(DeviceProtocolSpec.protocol_family, DeviceProtocolSpec.device_name, DeviceProtocolVersion.version_seq)
    )
    out = []
    for v, spec in r.all():
        out.append(
            {
                "id": v.id,
                "version_name": v.version_name,
                "availability_status": v.availability_status,
                "spec_id": spec.id,
                "device_id": spec.device_id,
                "device_name": spec.device_name,
                "protocol_family": spec.protocol_family,
                "ata_code": spec.ata_code,
                "label": f"[{(spec.protocol_family or '').upper()}] {spec.device_name} · {v.version_name}",
            }
        )
    return out
