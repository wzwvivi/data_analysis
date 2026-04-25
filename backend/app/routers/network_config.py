# -*- coding: utf-8 -*-
"""TSN 网络配置管理（网络团队；API 只读骨架，见 MR 说明）

MR1 范围：
- 让有 `network-config` 页面权限的角色能看到**所有**协议版本（含 PendingCode /
  Deprecated），按 `availability_status` 分组展示。
- 提供端口/字段下钻和 parser 家族清单，为后续 MR2（Draft 编辑）、MR3（代码就绪闸门）
  铺好接口形状。

写操作（Draft CRUD / 审批 / 激活 / 弃用）在后续 MR 里补齐，此处仅暂挂占位 404，
避免前端误用。
"""
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..deps import get_current_user
from ..models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_DEPRECATED,
    AVAILABILITY_PENDING_CODE,
    AVAILABILITY_STATUSES,
    DraftPortDefinition,
    PortDefinition,
    Protocol,
    ProtocolChangeRequest,
    ProtocolVersion,
    ProtocolVersionDraft,
    User,
)
from ..permissions import (
    PAGE_NETWORK_CONFIG,
    ROLE_ADMIN,
    ROLE_NETWORK_TEAM,
    has_page_access,
)
from ..services import ProtocolService
from ..services.protocol_service import PORT_FAMILY_MAP, resolve_port_family
from ..services.parsers import ParserRegistry
from ..services.protocol_draft_service import (
    DraftNotFoundError,
    DraftStateError,
    ProtocolDraftService,
    serialize_draft,
    serialize_field,
    serialize_port,
)
from ..services.protocol_check_service import run_static_check
from ..services import protocol_publish_service as publish_service
from ..services import protocol_activation_service as activation_service


def _require_network_config_access(user: User = Depends(get_current_user)) -> User:
    """只有拥有 network-config 页面权限的角色才能进。"""
    if not has_page_access(user.role or "", PAGE_NETWORK_CONFIG):
        raise HTTPException(status_code=403, detail="无权访问 TSN 网络配置管理")
    return user


router = APIRouter(
    prefix="/api/network-config",
    tags=["TSN 网络配置管理"],
    dependencies=[Depends(_require_network_config_access)],
)


def _serialize_version(v: ProtocolVersion, protocol: Optional[Protocol] = None) -> Dict:
    proto = protocol if protocol is not None else getattr(v, "protocol", None)
    return {
        "id": v.id,
        "protocol_id": v.protocol_id,
        "protocol_name": proto.name if proto else None,
        "version": v.version,
        "source_file": v.source_file,
        "description": v.description,
        "created_at": v.created_at,
        "availability_status": v.availability_status or AVAILABILITY_AVAILABLE,
        "activated_at": v.activated_at,
        "activated_by": v.activated_by,
        "forced_activation": bool(v.forced_activation),
        "port_count": len(v.ports) if getattr(v, "ports", None) else 0,
    }


@router.get("/parser-families")
async def list_parser_families(db: AsyncSession = Depends(get_db)):
    """列出当前后端已注册的协议族及其活跃 parser 清单。

    用于 Draft 端口编辑器的「协议族」下拉；族名权威来自 `ParserProfile.protocol_family`
    （DB，活跃条目）与 `ParserRegistry`（代码声明）的并集，以及历史硬编码 MAP 作为兜底。
    """
    from ..models import ParserProfile

    result = await db.execute(
        select(ParserProfile).where(ParserProfile.is_active.is_(True))
    )
    active_profiles = list(result.scalars().all())

    families: Dict[str, Dict] = {}
    for pp in active_profiles:
        fam = (pp.protocol_family or "").strip()
        if not fam:
            continue
        bucket = families.setdefault(
            fam,
            {"family": fam, "parsers": [], "source": "parser_profile"},
        )
        bucket["parsers"].append(
            {
                "id": pp.id,
                "parser_key": pp.parser_key,
                "name": pp.name,
                "version": pp.version,
                "device_model": pp.device_model,
            }
        )

    for fam in {v for v in PORT_FAMILY_MAP.values() if v}:
        families.setdefault(fam, {"family": fam, "parsers": [], "source": "legacy_map"})

    registry_keys = set(ParserRegistry.list_parsers())
    items = sorted(families.values(), key=lambda x: x["family"])
    for it in items:
        it["parser_keys_registered"] = sorted(
            {p["parser_key"] for p in it["parsers"] if p["parser_key"] in registry_keys}
        )

    return {"total": len(items), "items": items}


@router.get("/versions")
async def list_all_versions(
    status: Optional[str] = Query(
        default=None,
        description="按 availability_status 过滤：Available / PendingCode / Deprecated；不传则全部",
    ),
    db: AsyncSession = Depends(get_db),
):
    """网络团队视角的版本全量列表，含 PendingCode / Deprecated 供管理看板使用。"""
    if status and status not in AVAILABILITY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须为 {AVAILABILITY_STATUSES} 之一",
        )

    stmt = (
        select(ProtocolVersion)
        .options(
            selectinload(ProtocolVersion.protocol),
            selectinload(ProtocolVersion.ports),
        )
        .order_by(ProtocolVersion.created_at.desc())
    )
    if status:
        stmt = stmt.where(ProtocolVersion.availability_status == status)
    result = await db.execute(stmt)
    versions = list(result.scalars().all())

    grouped: Dict[str, List[Dict]] = {s: [] for s in AVAILABILITY_STATUSES}
    items: List[Dict] = []
    for v in versions:
        entry = _serialize_version(v)
        items.append(entry)
        bucket = v.availability_status or AVAILABILITY_AVAILABLE
        grouped.setdefault(bucket, []).append(entry)

    return {
        "total": len(items),
        "items": items,
        "grouped": {
            AVAILABILITY_AVAILABLE: grouped.get(AVAILABILITY_AVAILABLE, []),
            AVAILABILITY_PENDING_CODE: grouped.get(AVAILABILITY_PENDING_CODE, []),
            AVAILABILITY_DEPRECATED: grouped.get(AVAILABILITY_DEPRECATED, []),
        },
    }


async def _get_version_or_404(db: AsyncSession, version_id: int) -> ProtocolVersion:
    result = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.id == version_id)
        .options(
            selectinload(ProtocolVersion.protocol),
            selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields),
        )
    )
    pv = result.scalar_one_or_none()
    if pv is None:
        raise HTTPException(status_code=404, detail="TSN 网络协议版本不存在")
    return pv


@router.get("/versions/{version_id}")
async def get_version_detail(version_id: int, db: AsyncSession = Depends(get_db)):
    """版本详情：基本属性 + 端口统计 + 未命中协议族的端口清单（MR3 就绪检查会用）"""
    pv = await _get_version_or_404(db, version_id)

    ports = list(pv.ports or [])
    registry_keys = set(ParserRegistry.list_parsers())

    family_counter: Dict[str, int] = {}
    unknown_family_ports: List[int] = []
    for p in ports:
        fam = resolve_port_family(p.port_number, db_family=p.protocol_family)
        if not fam:
            unknown_family_ports.append(p.port_number)
            continue
        family_counter[fam] = family_counter.get(fam, 0) + 1

    return {
        **_serialize_version(pv),
        "ports_summary": {
            "total": len(ports),
            "by_family": [
                {"family": k, "port_count": v}
                for k, v in sorted(family_counter.items())
            ],
            "unknown_family_ports": sorted(unknown_family_ports),
        },
        "parser_registry_keys": sorted(registry_keys),
    }


@router.get("/versions/{version_id}/ports")
async def get_version_ports(version_id: int, db: AsyncSession = Depends(get_db)):
    """版本下所有端口（含 protocol_family）"""
    pv = await _get_version_or_404(db, version_id)
    ports = list(pv.ports or [])
    ports.sort(key=lambda p: p.port_number)

    icd_ext = (
        "message_id", "source_interface_id", "port_id_label", "diu_id",
        "diu_id_set", "diu_recv_mode", "tsn_source_ip", "diu_ip",
        "dataset_path", "data_real_path", "final_recv_device",
    )
    return {
        "version_id": version_id,
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
                "description": p.description,
                "protocol_family": p.protocol_family,
                "protocol_family_resolved": resolve_port_family(
                    p.port_number, db_family=p.protocol_family
                ),
                "port_role": getattr(p, "port_role", None),
                "field_count": len(p.fields) if p.fields else 0,
                **{attr: getattr(p, attr, None) for attr in icd_ext},
            }
            for p in ports
        ],
    }


@router.get("/versions/{version_id}/ports/{port_number}")
async def get_port_detail(
    version_id: int,
    port_number: int,
    db: AsyncSession = Depends(get_db),
):
    """端口详情（含字段定义），网络团队可查看任何状态的版本。"""
    await _get_version_or_404(db, version_id)
    service = ProtocolService(db)
    port = await service.get_port_by_number(version_id, port_number)
    if not port:
        raise HTTPException(status_code=404, detail="端口定义不存在")

    icd_ext = (
        "message_id", "source_interface_id", "port_id_label", "diu_id",
        "diu_id_set", "diu_recv_mode", "tsn_source_ip", "diu_ip",
        "dataset_path", "data_real_path", "final_recv_device",
    )
    return {
        "id": port.id,
        "port_number": port.port_number,
        "message_name": port.message_name,
        "source_device": port.source_device,
        "target_device": port.target_device,
        "multicast_ip": port.multicast_ip,
        "data_direction": port.data_direction,
        "period_ms": port.period_ms,
        "description": port.description,
        "protocol_family": port.protocol_family,
        "protocol_family_resolved": resolve_port_family(
            port.port_number, db_family=port.protocol_family
        ),
        "port_role": getattr(port, "port_role", None),
        **{attr: getattr(port, attr, None) for attr in icd_ext},
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
            for f in port.fields or []
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# 写侧：Draft CRUD + 审批流（MR2）
# ══════════════════════════════════════════════════════════════════════


def _require_network_team_write(user: User) -> User:
    """写操作：仅 network_team / admin 角色放行。"""
    role = (user.role or "").strip()
    if role not in (ROLE_ADMIN, ROLE_NETWORK_TEAM):
        raise HTTPException(status_code=403, detail="仅网络团队或管理员可执行该操作")
    return user


def _draft_payload(draft: ProtocolVersionDraft) -> Dict[str, Any]:
    data = serialize_draft(draft)
    data["ports"] = [serialize_port(p) for p in sorted(draft.ports, key=lambda x: x.port_number)] if draft.ports else []
    return data


def _fetch_draft_full(draft: ProtocolVersionDraft) -> Dict[str, Any]:
    data = serialize_draft(draft)
    data["ports"] = []
    for p in sorted(draft.ports, key=lambda x: x.port_number):
        entry = serialize_port(p)
        entry["fields"] = [serialize_field(f) for f in sorted(p.fields or [], key=lambda x: x.field_offset or 0)]
        data["ports"].append(entry)
    return data


@router.post("/drafts")
async def create_draft_from_version(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    source = (payload.get("source") or "clone").lower()
    if source != "clone":
        raise HTTPException(status_code=400, detail="此接口仅支持 source=clone；Excel 导入请走 /drafts/from-excel")
    base_version_id = payload.get("base_version_id")
    target_version = payload.get("target_version")
    name = payload.get("name")
    if not base_version_id or not target_version or not name:
        raise HTTPException(status_code=400, detail="base_version_id / target_version / name 均必填")
    service = ProtocolDraftService(db)
    try:
        draft = await service.create_from_version(
            base_version_id=int(base_version_id),
            target_version=str(target_version),
            name=str(name),
            description=payload.get("description"),
            created_by=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _draft_payload(draft)


@router.post("/drafts/from-excel")
async def create_draft_from_excel(
    protocol_id: int = Form(...),
    target_version: str = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    filename = file.filename or "icd.xlsx"
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xls 格式的 ICD 文件")
    content = await file.read()
    service = ProtocolDraftService(db)
    try:
        draft, stats = await service.create_from_excel(
            file_bytes=content,
            original_filename=filename,
            protocol_id=protocol_id,
            target_version=target_version,
            name=name,
            description=description,
            created_by=user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = _draft_payload(draft)
    data["import_stats"] = stats
    return data


@router.get("/drafts")
async def list_drafts(
    scope: str = Query("all", description="all | mine | pending"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ProtocolDraftService(db)
    if scope == "mine":
        drafts = await service.list_drafts(created_by=user.username)
    elif scope == "pending":
        drafts = await service.list_drafts(status="pending")
    else:
        drafts = await service.list_drafts()
    return {"total": len(drafts), "items": [_draft_payload(d) for d in drafts]}


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ProtocolDraftService(db)
    try:
        draft = await service.get_draft(draft_id, with_fields=True)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _fetch_draft_full(draft)


@router.patch("/drafts/{draft_id}")
async def update_draft(
    draft_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        draft = await service.update_draft_meta(
            draft_id,
            name=payload.get("name"),
            target_version=payload.get("target_version"),
            description=payload.get("description"),
        )
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DraftStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _draft_payload(draft)


@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        await service.delete_draft(draft_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DraftStateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "ok"}


# ── Draft 端口 CRUD ──
@router.post("/drafts/{draft_id}/ports")
async def add_draft_port(
    draft_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        dp = await service.add_port(draft_id, payload)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return serialize_port(dp)


@router.patch("/drafts/{draft_id}/ports/{port_id}")
async def update_draft_port(
    draft_id: int,
    port_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        dp = await service.update_port(draft_id, port_id, payload)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return serialize_port(dp)


@router.delete("/drafts/{draft_id}/ports/{port_id}")
async def delete_draft_port(
    draft_id: int,
    port_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        await service.delete_port(draft_id, port_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


@router.post("/drafts/{draft_id}/bulk-upsert-ports")
async def bulk_upsert_ports(
    draft_id: int,
    payload: List[Dict[str, Any]] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        return await service.bulk_upsert_ports(draft_id, payload)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Draft 字段 CRUD ──
@router.post("/drafts/{draft_id}/ports/{port_id}/fields")
async def add_draft_field(
    draft_id: int,
    port_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        f = await service.add_field(draft_id, port_id, payload)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return serialize_field(f)


@router.patch("/drafts/{draft_id}/ports/{port_id}/fields/{field_id}")
async def update_draft_field(
    draft_id: int,
    port_id: int,
    field_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        f = await service.update_field(draft_id, port_id, field_id, payload)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return serialize_field(f)


@router.delete("/drafts/{draft_id}/ports/{port_id}/fields/{field_id}")
async def delete_draft_field(
    draft_id: int,
    port_id: int,
    field_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    service = ProtocolDraftService(db)
    try:
        await service.delete_field(draft_id, port_id, field_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, DraftStateError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


# ── 检查 / diff / 导出 / 提交 ──
@router.post("/drafts/{draft_id}/check")
async def check_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return await run_static_check(db, draft_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/drafts/{draft_id}/diff")
async def draft_diff(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ProtocolDraftService(db)
    try:
        return await service.compute_diff(draft_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/drafts/{draft_id}/export-excel")
async def export_draft_excel(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ProtocolDraftService(db)
    try:
        content, filename = await service.export_excel(draft_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    import io
    from urllib.parse import quote
    buf = io.BytesIO(content)
    encoded = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={encoded}; filename*=UTF-8''{encoded}"
        },
    )


@router.post("/drafts/{draft_id}/submit")
async def submit_draft_api(
    draft_id: int,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    try:
        cr = await publish_service.submit_draft(
            db,
            draft_id,
            submitter_username=user.username,
            submitter_role=user.role or "",
            note=payload.get("note"),
            notify_teams=payload.get("notify_teams"),
        )
    except publish_service.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return publish_service.serialize_cr(cr)


# ── 审批流 ──
@router.get("/change-requests")
async def list_change_requests(
    scope: str = Query("all", description="all | mine | pending_for_me"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = await publish_service.list_change_requests(
        db,
        scope=scope,
        user_username=user.username,
        user_role=user.role or "",
    )
    return {
        "total": len(items),
        "items": [publish_service.serialize_cr(cr) for cr in items],
    }


@router.get("/change-requests/{cr_id}")
async def get_change_request(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        cr = await publish_service._get_cr(db, cr_id)
    except publish_service.PublishError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return publish_service.serialize_cr(cr)


@router.post("/change-requests/{cr_id}/sign-off")
async def sign_off_change_request(
    cr_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    decision = payload.get("decision")
    if not decision:
        raise HTTPException(status_code=400, detail="decision 必填")
    try:
        cr = await publish_service.sign_off_cr(
            db,
            cr_id,
            decision=str(decision),
            note=payload.get("note"),
            user_username=user.username,
            user_role=user.role or "",
        )
    except publish_service.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return publish_service.serialize_cr(cr)


@router.post("/versions/{version_id}/deprecate")
async def deprecate_version(
    version_id: int,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_network_team_write(user)
    pv = await _get_version_or_404(db, version_id)
    if pv.availability_status == AVAILABILITY_DEPRECATED:
        return {
            "status": "ok",
            "availability_status": pv.availability_status,
            "version_id": pv.id,
            "version": pv.version,
            "message": "already deprecated",
        }
    pv.availability_status = AVAILABILITY_DEPRECATED
    note = (payload.get("note") or "").strip()
    if note:
        base = pv.description or ""
        stamp = f"[deprecated by {user.username}] {note}"
        pv.description = f"{base}\n{stamp}" if base else stamp
    await db.commit()
    await db.refresh(pv)
    return {
        "status": "ok",
        "availability_status": pv.availability_status,
        "version_id": pv.id,
        "version": pv.version,
    }


@router.post("/change-requests/{cr_id}/publish")
async def publish_change_request(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if (user.role or "").strip() != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可发布")
    try:
        pv = await publish_service.publish_cr(
            db,
            cr_id,
            admin_username=user.username,
            admin_role=user.role or "",
        )
    except publish_service.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "status": "published",
        "protocol_version_id": pv.id,
        "availability_status": pv.availability_status,
        "version": pv.version,
    }


# ══════════════════════════════════════════════════════════════════════
# MR3: 激活闸门
# ══════════════════════════════════════════════════════════════════════


@router.get("/versions/{version_id}/activation-report")
async def get_activation_report(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """读取协议版本的就绪度体检报告；若不存在，自动触发一次生成。"""
    await _get_version_or_404(db, version_id)
    return await activation_service.get_activation_report(db, version_id, ensure=True)


@router.post("/versions/{version_id}/activation-report/refresh")
async def refresh_activation_report(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新生成 port_registry + 重跑体检（admin / network_team）。"""
    _require_network_team_write(user)
    await _get_version_or_404(db, version_id)
    result = await activation_service.refresh_activation_pipeline(db, version_id)
    return await activation_service.get_activation_report(db, version_id, ensure=False)


@router.post("/versions/{version_id}/activate")
async def activate_protocol_version(
    version_id: int,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把 PendingCode 版本切换为 Available（仅管理员）。"""
    force = bool(payload.get("force") or False)
    reason = payload.get("reason")
    pv = await activation_service.activate_version(
        db, version_id, user=user, force=force, reason=reason,
    )
    return {
        "status": "ok",
        "version_id": pv.id,
        "version": pv.version,
        "availability_status": pv.availability_status,
        "activated_at": pv.activated_at,
        "activated_by": pv.activated_by,
        "forced_activation": bool(pv.forced_activation),
    }


# ══════════════════════════════════════════════════════════════════════
# MR4: Bundle 查看接口（代码/数据分离）
# ══════════════════════════════════════════════════════════════════════


@router.get("/versions/{version_id}/bundle")
async def get_bundle(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回指定版本的 bundle.json 原始内容。缺失时自动尝试生成。"""
    from ..services.bundle import load_bundle, BundleNotFoundError
    from ..services.bundle import generator as bundle_generator
    from ..services.bundle.schema import bundle_to_dict

    await _get_version_or_404(db, version_id)
    try:
        bundle = load_bundle(version_id)
    except BundleNotFoundError:
        try:
            await bundle_generator.generate_bundle(db, version_id)
            bundle = load_bundle(version_id)
        except Exception as exc:
            raise HTTPException(
                status_code=404,
                detail=f"bundle v{version_id} 不存在且自动生成失败：{exc}",
            ) from exc
    return bundle_to_dict(bundle)


@router.post("/versions/{version_id}/bundle/refresh")
async def refresh_bundle(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """强制重新生成指定版本的 bundle.json（admin / network_team）。"""
    _require_network_team_write(user)
    from ..services.bundle import generator as bundle_generator

    await _get_version_or_404(db, version_id)
    artifact = await bundle_generator.generate_bundle(db, version_id)
    return {"status": "ok", "artifact": artifact}


@router.get("/versions/{version_id}/bundle/diff")
async def diff_bundle(
    version_id: int,
    against: int = Query(..., description="对比目标版本 ID"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """两个版本 bundle 的高层摘要 diff（端口新增/删除，字段改动等）。"""
    from ..services.bundle import load_bundle, BundleNotFoundError

    await _get_version_or_404(db, version_id)
    await _get_version_or_404(db, against)
    try:
        cur = load_bundle(version_id)
        base = load_bundle(against)
    except BundleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    cur_ports = set(cur.ports.keys())
    base_ports = set(base.ports.keys())
    ports_added = sorted(cur_ports - base_ports)
    ports_removed = sorted(base_ports - cur_ports)

    fields_changed: List[Dict[str, Any]] = []
    for pn in sorted(cur_ports & base_ports):
        cur_map = cur.fields_by_name(pn)
        base_map = base.fields_by_name(pn)
        added_f = sorted(set(cur_map.keys()) - set(base_map.keys()))
        removed_f = sorted(set(base_map.keys()) - set(cur_map.keys()))
        modified_f: List[str] = []
        for fn in set(cur_map.keys()) & set(base_map.keys()):
            a = cur_map[fn]
            b = base_map[fn]
            if (a.offset, a.length, a.data_type, a.byte_order) != (b.offset, b.length, b.data_type, b.byte_order):
                modified_f.append(fn)
        if added_f or removed_f or modified_f:
            fields_changed.append({
                "port": pn,
                "fields_added": added_f,
                "fields_removed": removed_f,
                "fields_modified": sorted(modified_f),
            })

    return {
        "current_version_id": version_id,
        "base_version_id": against,
        "ports_added": ports_added,
        "ports_removed": ports_removed,
        "fields_changed": fields_changed,
        "event_rules": {
            "current_templates": sorted(cur.event_rules.keys()),
            "base_templates": sorted(base.event_rules.keys()),
        },
    }


@router.get("/versions/{version_id}/bundle/meta")
async def get_bundle_meta(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回 bundle 的元数据卡片（SHA256 + 时间 + 端口/规则计数）。

    前端版本卡片用它做轻量展示，不需要拉整个 JSON。bundle 缺失时懒生成。
    """
    from ..services.bundle import (
        BundleNotFoundError,
        bundle_path_for,
        load_bundle,
    )
    from ..services.bundle import generator as bundle_generator
    from ..services.bundle.loader import sha256_path_for

    await _get_version_or_404(db, version_id)
    try:
        bundle = load_bundle(version_id)
    except BundleNotFoundError:
        try:
            await bundle_generator.generate_bundle(db, version_id)
            bundle = load_bundle(version_id)
        except Exception as exc:
            raise HTTPException(
                status_code=404,
                detail=f"bundle v{version_id} 不存在且自动生成失败：{exc}",
            ) from exc

    bundle_file = bundle_path_for(version_id)
    sha_file = sha256_path_for(version_id)
    sha256: Optional[str] = None
    if sha_file.is_file():
        try:
            sha256 = sha_file.read_text(encoding="utf-8").strip().split()[0] or None
        except Exception:
            sha256 = None

    rules_count = sum(len(v) for v in bundle.event_rules.values())
    return {
        "version_id": bundle.protocol_version_id,
        "protocol_version_name": bundle.protocol_version_name,
        "protocol_name": bundle.protocol_name,
        "schema_version": bundle.schema_version,
        "generated_at": bundle.generated_at.isoformat() + "Z",
        "sha256": sha256,
        "bundle_path": str(bundle_file),
        "bundle_bytes": bundle_file.stat().st_size if bundle_file.is_file() else None,
        "stats": {
            "ports": len(bundle.ports),
            "families": len(bundle.family_ports),
            "event_rules": rules_count,
            "event_rule_templates": list(bundle.event_rules.keys()),
        },
    }
