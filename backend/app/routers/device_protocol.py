# -*- coding: utf-8 -*-
"""设备协议（ARINC429 / CAN / RS422 …）路由

设计原则：
- 与 ``/api/network-config`` 平行；数据模型完全独立（DeviceProtocolSpec/Version/Draft）。
- 审批流走通用 ``ChangeRequestEngine``，``draft_kind=device_*``。
- 写权限：``device_team`` / ``admin``；会签权限按步骤角色在 service 层校验。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import DEVICE_PROTOCOL_FAMILIES, User
from ..permissions import (
    PAGE_DEVICE_PROTOCOL,
    ROLE_ADMIN,
    ROLE_DEVICE_TEAM,
    has_page_access,
)
from ..services import device_protocol_service as dps
from ..services.device_protocol_service import DeviceProtocolError
from ..services.protocol_family import get_family_handler


def _require_device_protocol_access(user: User = Depends(get_current_user)) -> User:
    if not has_page_access(user.role or "", PAGE_DEVICE_PROTOCOL):
        raise HTTPException(status_code=403, detail="无权访问设备协议管理")
    return user


def _require_device_write(user: User) -> None:
    role = (user.role or "").strip()
    if role not in (ROLE_ADMIN, ROLE_DEVICE_TEAM):
        raise HTTPException(status_code=403, detail="仅设备团队或管理员可执行该操作")


router = APIRouter(
    prefix="/api/device-protocol",
    tags=["设备协议管理"],
    dependencies=[Depends(_require_device_protocol_access)],
)


# ═════════════════════════ 基础信息 ═════════════════════════


@router.get("/families")
async def list_families():
    """列出平台内置的所有设备协议族"""
    items = []
    for fam in DEVICE_PROTOCOL_FAMILIES:
        h = get_family_handler(fam)
        empty = h.new_empty_spec(device_name="sample", version_name="V1.0")
        items.append(
            {
                "family": fam,
                "display_name": fam.upper(),
                "spec_schema_hint": list(empty.keys()),
            }
        )
    return {"total": len(items), "items": items}


@router.get("/tree")
async def get_device_tree(
    family: Optional[str] = Query(None),
    group_by: str = Query("ata", description="ata | family"),
    db: AsyncSession = Depends(get_db),
):
    """设备树。

    - ``group_by=ata`` (默认)：ATA 系统 → 设备（设备节点上挂协议族 tag）
    - ``group_by=family``：协议族 → ATA → 设备（旧行为，便于按协议族对比）
    """
    if group_by not in ("ata", "family"):
        raise HTTPException(status_code=400, detail="group_by 必须是 ata 或 family")
    return {
        "group_by": group_by,
        "items": await dps.build_device_tree(db, family=family, group_by=group_by),
    }


@router.get("/ata-systems")
async def list_ata_systems(db: AsyncSession = Depends(get_db)):
    """列出现有 ATA 系统（按 spec.ata_code 去重聚合）"""
    items = await dps.list_ata_systems(db)
    return {"total": len(items), "items": items}


@router.get("/next-device-number")
async def next_device_number(
    ata_code: str = Query(..., description="如 ata32"),
    db: AsyncSession = Depends(get_db),
):
    """给定 ATA 系统，算下一个设备序号 + 推出标准 device_id 前缀"""
    return await dps.compute_next_device_number(db, ata_code)


@router.post("/preview-device-identity")
async def preview_device_identity(
    payload: Dict[str, Any] = Body(...),
):
    """给前端实时预览标准化后的 device_id / 完整设备名（例如 ata32_32_4 / 32-4-xxx-429）"""
    try:
        identity = dps.build_auto_device_identity(
            ata_code=str(payload.get("ata_code") or "").strip(),
            device_number=(payload.get("device_number") or None) or None,
            device_name=str(payload.get("device_name") or "").strip(),
            protocol_family=str(payload.get("protocol_family") or "arinc429"),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
    return identity


# ═════════════════════════ Spec ═════════════════════════


@router.get("/specs")
async def list_specs(
    family: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    items = await dps.list_specs(db, family=family, include_counts=True)
    return {"total": len(items), "items": items}


@router.get("/specs/{spec_id}")
async def get_spec_detail(spec_id: int, db: AsyncSession = Depends(get_db)):
    spec = await dps.get_spec_by_id(db, spec_id, with_versions=True)
    if not spec:
        raise HTTPException(status_code=404, detail="设备 spec 不存在")
    versions = sorted(spec.versions or [], key=lambda v: v.version_seq or 0, reverse=True)
    handler = get_family_handler(spec.protocol_family)
    latest_spec_json = versions[0].spec_json if versions else None
    return {
        "spec": dps._spec_to_dict(spec, include_counts=False),
        "versions": [dps.serialize_version(v) for v in versions],
        "summary": handler.summarize_spec(latest_spec_json or {}),
        "labels_view": handler.labels_view(latest_spec_json or {}) if latest_spec_json else [],
        "latest_spec_json": latest_spec_json,
        "latest_version_id": versions[0].id if versions else None,
        "latest_version_name": versions[0].version_name if versions else None,
    }


@router.get("/versions/{version_id}")
async def get_version_detail(version_id: int, db: AsyncSession = Depends(get_db)):
    v = await dps.get_version(db, version_id)
    if not v:
        raise HTTPException(status_code=404, detail="设备协议版本不存在")
    spec = await dps.get_spec_by_id(db, v.spec_id, with_versions=False)
    handler = get_family_handler(spec.protocol_family) if spec else None
    return {
        **dps.serialize_version(v),
        "protocol_family": spec.protocol_family if spec else None,
        "device_id": spec.device_id if spec else None,
        "device_name": spec.device_name if spec else None,
        "spec_json": v.spec_json,
        "labels_view": handler.labels_view(v.spec_json or {}) if handler else [],
        "summary": handler.summarize_spec(v.spec_json or {}) if handler else {},
    }


# ═════════════════════════ Draft ═════════════════════════


@router.post("/drafts")
async def create_draft(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建草稿。``target_version`` 不再需要前端传，发布时由后端自动升版。

    - ``source=clone``：基于已发布版本克隆；必填 ``base_version_id``
    - ``source=scratch``：新建设备；必填 ``protocol_family / device_id / device_name``
    - ``source=edit_spec``：修改现有设备协议一键入口；必填 ``spec_id``，后端自动基于最新版本克隆
    """
    _require_device_write(user)
    source = (payload.get("source") or "clone").lower()

    try:
        if source == "clone":
            base_version_id = payload.get("base_version_id")
            if not base_version_id:
                raise HTTPException(
                    status_code=400, detail="source=clone 时 base_version_id 必填"
                )
            draft = await dps.create_draft_from_version(
                db,
                base_version_id=int(base_version_id),
                name=payload.get("name"),
                description=payload.get("description"),
                created_by=user.username,
            )
        elif source == "edit_spec":
            spec_id = payload.get("spec_id")
            if not spec_id:
                raise HTTPException(
                    status_code=400, detail="source=edit_spec 时 spec_id 必填"
                )
            draft = await dps.create_or_resume_draft_for_spec(
                db,
                spec_id=int(spec_id),
                created_by=user.username,
            )
        elif source == "scratch":
            family = payload.get("protocol_family")
            device_id = payload.get("device_id")
            device_name = payload.get("device_name")
            if not family or not device_id or not device_name:
                raise HTTPException(
                    status_code=400,
                    detail="source=scratch 时 protocol_family / device_id / device_name 必填",
                )
            draft = await dps.create_draft_scratch_new_device(
                db,
                protocol_family=family,
                ata_code=payload.get("ata_code"),
                device_id=device_id,
                device_name=device_name,
                parent_path=payload.get("parent_path"),
                name=payload.get("name"),
                description=payload.get("description"),
                created_by=user.username,
            )
        else:
            raise HTTPException(status_code=400, detail=f"未知 source={source}")
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return dps.serialize_draft(draft)


@router.post("/specs/{spec_id}/edit-draft")
async def edit_spec_draft(
    spec_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """「修改协议」一键入口：对某设备自动复用/创建一条可编辑草稿并返回"""
    _require_device_write(user)
    try:
        draft = await dps.create_or_resume_draft_for_spec(
            db, spec_id=spec_id, created_by=user.username
        )
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dps.serialize_draft(draft)


@router.get("/drafts")
async def list_drafts(
    scope: str = Query("all", description="all | mine"),
    family: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    spec_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    drafts = await dps.list_drafts(
        db,
        family=family,
        spec_id=spec_id,
        status=status,
        created_by=user.username if scope == "mine" else None,
    )
    return {"total": len(drafts), "items": [dps.serialize_draft(d) for d in drafts]}


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    try:
        draft = await dps._get_draft_or_raise(db, draft_id)
    except DeviceProtocolError as e:
        raise HTTPException(status_code=404, detail=str(e))
    handler = get_family_handler(draft.protocol_family)
    return {
        **dps.serialize_draft(draft),
        "spec_json": draft.spec_json,
        "labels_view": handler.labels_view(draft.spec_json or {}),
        "summary": handler.summarize_spec(draft.spec_json or {}),
    }


@router.patch("/drafts/{draft_id}")
async def update_draft(
    draft_id: int,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_device_write(user)
    try:
        draft = await dps.update_draft_spec_json(
            db,
            draft_id,
            spec_json=payload.get("spec_json") or {},
            name=payload.get("name"),
            description=payload.get("description"),
        )
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dps.serialize_draft(draft)


@router.delete("/drafts/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_device_write(user)
    try:
        await dps.delete_draft(db, draft_id)
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok"}


@router.post("/drafts/{draft_id}/check")
async def check_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await dps.run_draft_check(db, draft_id)
    except DeviceProtocolError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/drafts/{draft_id}/diff")
async def draft_diff(draft_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await dps.compute_draft_diff(db, draft_id)
    except DeviceProtocolError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/drafts/{draft_id}/submit")
async def submit_draft(
    draft_id: int,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_device_write(user)
    try:
        cr = await dps.submit_draft(
            db,
            draft_id,
            submitter_username=user.username,
            submitter_role=user.role or "",
            note=payload.get("note"),
        )
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dps.serialize_cr(cr)


# ═════════════════════════ ChangeRequest ═════════════════════════


@router.get("/change-requests")
async def list_change_requests(
    scope: str = Query("all", description="all | mine | pending_for_me"),
    family: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = await dps.list_change_requests(
        db,
        scope=scope,
        family=family,
        user_username=user.username,
        user_role=user.role or "",
    )
    return {"total": len(items), "items": [dps.serialize_cr(cr) for cr in items]}


@router.get("/change-requests/{cr_id}")
async def get_change_request(cr_id: int, db: AsyncSession = Depends(get_db)):
    try:
        cr = await dps._get_cr_or_raise(db, cr_id)
    except DeviceProtocolError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if cr.device_draft_id is None:
        raise HTTPException(
            status_code=400,
            detail="该审批流不是设备协议类型（请走 /api/network-config）",
        )
    return dps.serialize_cr(cr)


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
        cr = await dps.sign_off_cr(
            db,
            cr_id,
            decision=str(decision),
            note=payload.get("note"),
            user_username=user.username,
            user_role=user.role or "",
        )
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dps.serialize_cr(cr)


@router.post("/change-requests/{cr_id}/publish")
async def publish_change_request(
    cr_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if (user.role or "").strip() != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="仅管理员可发布")
    try:
        result = await dps.publish_cr(
            db,
            cr_id,
            admin_username=user.username,
            admin_role=user.role or "",
        )
    except DeviceProtocolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result
