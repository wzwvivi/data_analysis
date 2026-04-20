# -*- coding: utf-8 -*-
"""设备协议（ARINC429 / CAN / RS422 …）一站式服务

包含：
- Spec / Version / Draft CRUD
- Draft 静态检查 + diff（委托协议族 handler）
- submit / sign-off / publish 全流程（走 ChangeRequestEngine）
- publish 时附带 Git 导出副本（方案 2）
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..approval_policy import get_chain_for_kind
from ..models import (
    APPROVAL_APPROVE,
    APPROVAL_PENDING,
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_DEPRECATED,
    AVAILABILITY_PENDING_CODE,
    ChangeRequestApproval,
    CR_STATUS_APPROVED,
    CR_STATUS_PENDING,
    CR_STATUS_PUBLISHED,
    CR_STATUS_REJECTED,
    DEVICE_PROTOCOL_FAMILIES,
    DEVICE_SPEC_ACTIVE,
    DEVICE_SPEC_DEPRECATED,
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PUBLISHED,
    DRAFT_STATUS_REJECTED,
    DeviceProtocolDraft,
    DeviceProtocolSpec,
    DeviceProtocolVersion,
    GIT_EXPORT_EXPORTED,
    GIT_EXPORT_FAILED,
    GIT_EXPORT_SKIPPED,
    GIT_EXPORT_PENDING,
    ProtocolChangeRequest,
    draft_kind_for_family,
)
from .approval import ChangeRequestEngine, EnginePublishError, PublishedOutcome
from .git_export import ExportResult, GitExporter, get_git_exporter
from .protocol_family import FamilyHandler, get_family_handler


class DeviceProtocolError(Exception):
    pass


# ═════════════════════════ Spec / Version CRUD ═════════════════════════


def _ensure_family_supported(family: str) -> None:
    if family not in DEVICE_PROTOCOL_FAMILIES:
        raise DeviceProtocolError(
            f"不支持的协议族：{family}（支持 {', '.join(DEVICE_PROTOCOL_FAMILIES)}）"
        )


# ═════════════════════════ 版本号工具 ═════════════════════════


_VERSION_RE = re.compile(r"^\s*([Vv])?(\d+)(?:\.(\d+))?(?:\.(\d+))?\s*$")


def increment_major_version(version_str: Optional[str]) -> str:
    """与桌面 ``device_manager.increment_version`` 对齐：主版本 +1，副号归零。

    - V1.0 → V2.0
    - v3 → V4.0
    - 非法/空 → V1.0
    """
    if not version_str:
        return "V1.0"
    m = _VERSION_RE.match(str(version_str))
    if not m:
        return "V1.0"
    major = int(m.group(2)) + 1
    return f"V{major}.0"


async def compute_next_version_name(
    db: AsyncSession, spec_id: Optional[int], fallback: str = "V1.0"
) -> str:
    """给定 spec，算"下一次 publish 的版本号"。

    规则：取 spec 下 version_seq 最大的版本，主版本号 +1。若 spec 还没有任何
    版本（新建设备场景），返回 fallback（默认 V1.0）。
    """
    if not spec_id:
        return fallback
    res = await db.execute(
        select(DeviceProtocolVersion)
        .where(DeviceProtocolVersion.spec_id == spec_id)
        .order_by(DeviceProtocolVersion.version_seq.desc())
        .limit(1)
    )
    latest = res.scalar_one_or_none()
    if not latest:
        return fallback
    return increment_major_version(latest.version_name)


# ═════════════════════════ ATA / 设备编号 ═════════════════════════


async def list_ata_systems(db: AsyncSession) -> List[Dict[str, Any]]:
    """列出现有 ATA 系统（以 DeviceProtocolSpec.ata_code 去重聚合）。"""
    res = await db.execute(
        select(
            DeviceProtocolSpec.ata_code,
            func.count(DeviceProtocolSpec.id).label("device_count"),
        )
        .group_by(DeviceProtocolSpec.ata_code)
        .order_by(DeviceProtocolSpec.ata_code)
    )
    items: List[Dict[str, Any]] = []
    for ata_code, device_count in res.all():
        code = ata_code or ""
        # 尝试从 code 里提取"ata32"并推出显示名
        label = code.upper() if code else "其他"
        items.append(
            {
                "ata_code": code or None,
                "display_name": label,
                "device_count": int(device_count or 0),
            }
        )
    return items


_ATA_PREFIX_RE = re.compile(r"^ata(\d+)$", re.IGNORECASE)


def _extract_system_prefix(ata_code: Optional[str]) -> Optional[str]:
    if not ata_code:
        return None
    m = _ATA_PREFIX_RE.match(ata_code.strip())
    if m:
        return m.group(1)
    return None


async def compute_next_device_number(
    db: AsyncSession, ata_code: str
) -> Dict[str, Any]:
    """为 ATA 系统算下一个设备序号，返回系统 prefix + next_seq。

    若 ata_code 是 ata32，prefix=32；扫 spec.device_name 形如 32-1 / 32-2 / 32-4 的，
    取 max+1。找不到任何 → next_seq=1。
    """
    prefix = _extract_system_prefix(ata_code)
    res = await db.execute(
        select(DeviceProtocolSpec)
        .where(DeviceProtocolSpec.ata_code == ata_code)
    )
    specs = list(res.scalars().all())
    max_seq = 0
    if prefix:
        pat = re.compile(rf"^{re.escape(prefix)}-(\d+)")
        for s in specs:
            m = pat.match(s.device_name or "")
            if m:
                try:
                    max_seq = max(max_seq, int(m.group(1)))
                except ValueError:
                    pass
            # 也尝试从 device_id 末尾提取
            m2 = re.search(rf"{re.escape(prefix)}_(\d+)$", s.device_id or "")
            if m2:
                try:
                    max_seq = max(max_seq, int(m2.group(1)))
                except ValueError:
                    pass
    return {
        "ata_code": ata_code,
        "system_prefix": prefix,
        "next_seq": max_seq + 1,
        "current_max": max_seq,
        "existing_count": len(specs),
    }


def build_auto_device_identity(
    *,
    ata_code: str,
    device_number: Optional[str],
    device_name: str,
    protocol_family: str,
) -> Dict[str, str]:
    """对齐桌面"32-1-转弯控制单元-429""ata32_32_1"命名规则，算出 device_id / 完整名."""
    proto_tag = {"arinc429": "429", "rs422": "422", "can": "CAN"}.get(
        protocol_family, protocol_family.upper()
    )
    prefix = _extract_system_prefix(ata_code) or ""
    if device_number:
        full_name = f"{device_number}-{device_name}-{proto_tag}"
        num_norm = device_number.replace("-", "_")
        if ata_code:
            device_id = f"{ata_code}_{num_norm}"
        else:
            device_id = f"dev_{num_norm}"
    else:
        full_name = f"{device_name}-{proto_tag}" if device_name else proto_tag
        safe = re.sub(r"[^\w]", "_", device_name or "dev").strip("_").lower()[:20] or "dev"
        ts = str(int(datetime.utcnow().timestamp()) % 10000)
        device_id = (
            f"{ata_code}_{safe}_{ts}" if ata_code else f"dev_{safe}_{ts}"
        )
    return {
        "device_id": device_id,
        "full_device_name": full_name,
        "protocol_tag": proto_tag,
    }


async def list_specs(
    db: AsyncSession,
    *,
    family: Optional[str] = None,
    include_counts: bool = True,
) -> List[Dict[str, Any]]:
    stmt = select(DeviceProtocolSpec).order_by(
        DeviceProtocolSpec.protocol_family, DeviceProtocolSpec.device_id
    )
    if family:
        stmt = stmt.where(DeviceProtocolSpec.protocol_family == family)
    stmt = stmt.options(selectinload(DeviceProtocolSpec.versions))
    res = await db.execute(stmt)
    specs = list(res.scalars().all())
    items: List[Dict[str, Any]] = []
    for s in specs:
        items.append(_spec_to_dict(s, include_counts=include_counts))
    return items


async def get_spec_by_id(
    db: AsyncSession, spec_id: int, *, with_versions: bool = True
) -> Optional[DeviceProtocolSpec]:
    stmt = select(DeviceProtocolSpec).where(DeviceProtocolSpec.id == spec_id)
    if with_versions:
        stmt = stmt.options(selectinload(DeviceProtocolSpec.versions))
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def create_spec(
    db: AsyncSession,
    *,
    protocol_family: str,
    device_id: str,
    device_name: str,
    ata_code: Optional[str] = None,
    parent_path: Optional[List[str]] = None,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
) -> DeviceProtocolSpec:
    _ensure_family_supported(protocol_family)
    # 唯一约束（family, device_id）
    exists = await db.execute(
        select(DeviceProtocolSpec).where(
            DeviceProtocolSpec.protocol_family == protocol_family,
            DeviceProtocolSpec.device_id == device_id,
        )
    )
    if exists.scalar_one_or_none():
        raise DeviceProtocolError(f"设备 {device_id}（{protocol_family}）已存在")

    spec = DeviceProtocolSpec(
        protocol_family=protocol_family,
        device_id=device_id,
        device_name=device_name,
        ata_code=ata_code,
        parent_path=parent_path,
        description=description,
        status=DEVICE_SPEC_ACTIVE,
        created_by=created_by,
    )
    db.add(spec)
    await db.commit()
    await db.refresh(spec)
    return spec


async def get_versions_for_spec(
    db: AsyncSession, spec_id: int
) -> List[DeviceProtocolVersion]:
    res = await db.execute(
        select(DeviceProtocolVersion)
        .where(DeviceProtocolVersion.spec_id == spec_id)
        .order_by(DeviceProtocolVersion.version_seq.desc())
    )
    return list(res.scalars().all())


async def get_version(
    db: AsyncSession, version_id: int
) -> Optional[DeviceProtocolVersion]:
    res = await db.execute(
        select(DeviceProtocolVersion).where(DeviceProtocolVersion.id == version_id)
    )
    return res.scalar_one_or_none()


async def build_device_tree(
    db: AsyncSession,
    *,
    family: Optional[str] = None,
    group_by: str = "ata",
) -> List[Dict[str, Any]]:
    """构造设备树。

    - ``group_by='ata'``（默认，对齐桌面平台）：ATA 系统 → 设备；每个设备节点
      挂协议族 tag，同一系统下 429/422/CAN 可以混合。
    - ``group_by='family'``：协议族 → ATA → 设备（之前的行为，便于按协议族对比）。

    说明：按用户要求，**设备树节点不再显示任何审批/状态信息**，只返回设备身份信息
    让前端决定展示（协议族 tag + 设备名 + ATA）。
    """
    items = await list_specs(db, family=family, include_counts=True)

    def _device_leaf(dev: Dict[str, Any], ata: str) -> Dict[str, Any]:
        return {
            "key": f"spec:{dev['id']}",
            "type": "device",
            "spec_id": dev["id"],
            "device_id": dev["device_id"],
            "family": dev["protocol_family"],
            "ata_code": ata,
            "title": dev["device_name"],
        }

    if group_by == "family":
        grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for it in items:
            fam = it["protocol_family"]
            ata = it.get("ata_code") or "其他"
            grouped.setdefault(fam, {}).setdefault(ata, []).append(it)

        tree: List[Dict[str, Any]] = []
        for fam in sorted(grouped.keys()):
            fam_node = {
                "key": f"family:{fam}",
                "type": "family",
                "family": fam,
                "title": fam.upper(),
                "children": [],
            }
            for ata in sorted(grouped[fam].keys()):
                ata_node = {
                    "key": f"family:{fam}:ata:{ata}",
                    "type": "ata",
                    "family": fam,
                    "ata_code": ata,
                    "title": ata,
                    "children": [],
                }
                for dev in sorted(
                    grouped[fam][ata], key=lambda x: (x["device_name"], x["device_id"])
                ):
                    ata_node["children"].append(_device_leaf(dev, ata))
                fam_node["children"].append(ata_node)
            tree.append(fam_node)
        return tree

    # 默认：group_by == 'ata'
    ata_grouped: Dict[str, List[Dict[str, Any]]] = {}
    for it in items:
        ata = it.get("ata_code") or "其他"
        ata_grouped.setdefault(ata, []).append(it)

    tree: List[Dict[str, Any]] = []
    for ata in sorted(ata_grouped.keys()):
        ata_node = {
            "key": f"ata:{ata}",
            "type": "ata",
            "ata_code": ata,
            "title": ata.upper() if ata and ata != "其他" else ata,
            "children": [],
        }
        for dev in sorted(
            ata_grouped[ata], key=lambda x: (x["device_name"], x["device_id"])
        ):
            ata_node["children"].append(_device_leaf(dev, ata))
        tree.append(ata_node)
    return tree


def _spec_to_dict(
    spec: DeviceProtocolSpec, *, include_counts: bool = True
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": spec.id,
        "protocol_family": spec.protocol_family,
        "device_id": spec.device_id,
        "device_name": spec.device_name,
        "ata_code": spec.ata_code,
        "parent_path": spec.parent_path or [],
        "description": spec.description,
        "status": spec.status,
        "current_version_id": spec.current_version_id,
        "created_by": spec.created_by,
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }
    if include_counts and getattr(spec, "versions", None) is not None:
        versions = list(spec.versions or [])
        data["version_count"] = len(versions)
        if versions:
            latest = max(versions, key=lambda v: v.version_seq or 0)
            data["latest_version"] = {
                "id": latest.id,
                "version_name": latest.version_name,
                "availability_status": latest.availability_status,
                "created_at": latest.created_at,
                "git_export_status": latest.git_export_status,
            }
    return data


def serialize_version(v: DeviceProtocolVersion) -> Dict[str, Any]:
    return {
        "id": v.id,
        "spec_id": v.spec_id,
        "version_name": v.version_name,
        "version_seq": v.version_seq,
        "description": v.description,
        "availability_status": v.availability_status,
        "activated_at": v.activated_at,
        "activated_by": v.activated_by,
        "git_commit_hash": v.git_commit_hash,
        "git_tag": v.git_tag,
        "git_export_status": v.git_export_status,
        "git_export_error": v.git_export_error,
        "git_exported_at": v.git_exported_at,
        "created_by": v.created_by,
        "created_at": v.created_at,
        "published_from_draft_id": v.published_from_draft_id,
    }


def serialize_draft(draft: DeviceProtocolDraft) -> Dict[str, Any]:
    return {
        "id": draft.id,
        "spec_id": draft.spec_id,
        "base_version_id": draft.base_version_id,
        "protocol_family": draft.protocol_family,
        "source_type": draft.source_type,
        "name": draft.name,
        "target_version": draft.target_version,
        "description": draft.description,
        "status": draft.status,
        "submit_note": draft.submit_note,
        "pending_spec_meta": draft.pending_spec_meta,
        "created_by": draft.created_by,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "published_version_id": draft.published_version_id,
    }


# ═════════════════════════ Draft CRUD ═════════════════════════


async def _get_draft_or_raise(
    db: AsyncSession, draft_id: int
) -> DeviceProtocolDraft:
    res = await db.execute(
        select(DeviceProtocolDraft)
        .where(DeviceProtocolDraft.id == draft_id)
        .options(selectinload(DeviceProtocolDraft.change_requests))
    )
    d = res.scalar_one_or_none()
    if not d:
        raise DeviceProtocolError(f"设备协议草稿 {draft_id} 不存在")
    return d


async def list_drafts(
    db: AsyncSession,
    *,
    family: Optional[str] = None,
    spec_id: Optional[int] = None,
    created_by: Optional[str] = None,
    status: Optional[str] = None,
) -> List[DeviceProtocolDraft]:
    stmt = select(DeviceProtocolDraft).order_by(
        DeviceProtocolDraft.updated_at.desc()
    )
    if family:
        stmt = stmt.where(DeviceProtocolDraft.protocol_family == family)
    if spec_id is not None:
        stmt = stmt.where(DeviceProtocolDraft.spec_id == spec_id)
    if created_by:
        stmt = stmt.where(DeviceProtocolDraft.created_by == created_by)
    if status:
        stmt = stmt.where(DeviceProtocolDraft.status == status)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def _assert_no_active_draft_for_spec(
    db: AsyncSession, spec_id: int, exclude_draft_id: Optional[int] = None
) -> None:
    """每个设备同一时刻最多一条活动草稿（draft/pending）"""
    stmt = (
        select(DeviceProtocolDraft)
        .where(DeviceProtocolDraft.spec_id == spec_id)
        .where(DeviceProtocolDraft.status.in_((DRAFT_STATUS_DRAFT, DRAFT_STATUS_PENDING)))
    )
    if exclude_draft_id is not None:
        stmt = stmt.where(DeviceProtocolDraft.id != exclude_draft_id)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        raise DeviceProtocolError(
            f"该设备已有活动草稿（#{existing.id}，状态={existing.status}），"
            f"请先发布/驳回/删除它，再创建新的"
        )


async def create_draft_from_version(
    db: AsyncSession,
    *,
    base_version_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
) -> DeviceProtocolDraft:
    """基于某个已发布版本创建草稿。

    - 不再要求前端传 ``target_version``：发布时自动升主版本号（V1.0→V2.0→V3.0）
    - 每个 spec 同时只能有 1 条 draft/pending 草稿，由业务层强校验
    """
    base = await get_version(db, base_version_id)
    if not base:
        raise DeviceProtocolError(f"基础版本 {base_version_id} 不存在")
    spec = await get_spec_by_id(db, base.spec_id, with_versions=False)
    if not spec:
        raise DeviceProtocolError(f"基础版本对应的设备 spec_id={base.spec_id} 已不存在")

    await _assert_no_active_draft_for_spec(db, spec.id)

    family = spec.protocol_family
    handler = get_family_handler(family)
    spec_json = handler.normalize_spec(base.spec_json or {})
    spec_json.setdefault("protocol_meta", {})
    if description:
        spec_json["protocol_meta"]["description"] = description

    draft_name = (name or f"{spec.device_name} 修订草稿").strip() or f"{spec.device_name} 修订草稿"

    draft = DeviceProtocolDraft(
        spec_id=spec.id,
        base_version_id=base.id,
        protocol_family=family,
        source_type="clone",
        name=draft_name,
        target_version=None,  # publish 时自动算下一个版本号
        description=description or f"基于 {base.version_name} 创建",
        spec_json=spec_json,
        status=DRAFT_STATUS_DRAFT,
        created_by=created_by,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


async def create_or_resume_draft_for_spec(
    db: AsyncSession,
    *,
    spec_id: int,
    created_by: Optional[str] = None,
) -> DeviceProtocolDraft:
    """"修改协议"一键入口：针对某个 spec 找/建一条 draft。

    - 若 spec 已有状态为 ``draft`` 的草稿 → 直接复用（允许继续编辑）
    - 若已有 ``pending`` 草稿 → 抛错（审批中，锁定）
    - 否则基于最新版本克隆一份新草稿
    """
    spec = await get_spec_by_id(db, spec_id, with_versions=True)
    if not spec:
        raise DeviceProtocolError(f"设备 spec_id={spec_id} 不存在")

    res = await db.execute(
        select(DeviceProtocolDraft)
        .where(DeviceProtocolDraft.spec_id == spec.id)
        .where(DeviceProtocolDraft.status.in_((DRAFT_STATUS_DRAFT, DRAFT_STATUS_PENDING)))
        .order_by(DeviceProtocolDraft.updated_at.desc())
    )
    active = res.scalars().first()
    if active:
        if active.status == DRAFT_STATUS_DRAFT:
            return active
        raise DeviceProtocolError(
            f"该设备已有审批中的草稿（#{active.id}），请等其完结再修改"
        )

    versions = sorted(spec.versions or [], key=lambda v: v.version_seq or 0, reverse=True)
    if not versions:
        # 还没有任何版本：直接 scratch 一条空 draft
        handler = get_family_handler(spec.protocol_family)
        empty_spec_json = handler.new_empty_spec(
            device_name=spec.device_name,
            version_name="V1.0",
            description=spec.description,
        )
        draft = DeviceProtocolDraft(
            spec_id=spec.id,
            base_version_id=None,
            protocol_family=spec.protocol_family,
            source_type="scratch",
            name=f"{spec.device_name} 初始草稿",
            target_version=None,
            description=spec.description,
            spec_json=empty_spec_json,
            status=DRAFT_STATUS_DRAFT,
            created_by=created_by,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        return draft

    latest = versions[0]
    return await create_draft_from_version(
        db,
        base_version_id=latest.id,
        name=None,
        description=None,
        created_by=created_by,
    )


async def create_draft_scratch_new_device(
    db: AsyncSession,
    *,
    protocol_family: str,
    ata_code: Optional[str],
    device_id: str,
    device_name: str,
    parent_path: Optional[List[str]],
    name: Optional[str] = None,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
) -> DeviceProtocolDraft:
    """新建设备场景：由前端上传"系统+协议+设备名"等信息，后端自动算 device_id（若未给），
    发布时自动升为 V1.0，免掉 target_version 表单项。
    """
    _ensure_family_supported(protocol_family)
    exists = await db.execute(
        select(DeviceProtocolSpec).where(
            DeviceProtocolSpec.protocol_family == protocol_family,
            DeviceProtocolSpec.device_id == device_id,
        )
    )
    if exists.scalar_one_or_none():
        raise DeviceProtocolError(
            f"设备 {device_id}（{protocol_family}）已存在，请基于其版本修改"
        )

    handler = get_family_handler(protocol_family)
    spec_json = handler.new_empty_spec(
        device_name=device_name,
        version_name="V1.0",
        description=description,
    )
    draft = DeviceProtocolDraft(
        spec_id=None,
        base_version_id=None,
        protocol_family=protocol_family,
        source_type="scratch",
        name=name or f"新建设备 {device_name}",
        target_version=None,
        description=description,
        spec_json=spec_json,
        pending_spec_meta={
            "ata_code": ata_code,
            "device_id": device_id,
            "device_name": device_name,
            "parent_path": parent_path or [],
        },
        status=DRAFT_STATUS_DRAFT,
        created_by=created_by,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


async def update_draft_spec_json(
    db: AsyncSession,
    draft_id: int,
    *,
    spec_json: Dict[str, Any],
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> DeviceProtocolDraft:
    draft = await _get_draft_or_raise(db, draft_id)
    if draft.status != DRAFT_STATUS_DRAFT:
        raise DeviceProtocolError(
            f"草稿当前状态 {draft.status}，不可编辑（仅 draft 态可写）"
        )
    handler = get_family_handler(draft.protocol_family)
    draft.spec_json = handler.normalize_spec(spec_json or {})
    if name is not None:
        draft.name = name
    if description is not None:
        draft.description = description
    draft.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(draft)
    return draft


async def delete_draft(db: AsyncSession, draft_id: int) -> None:
    draft = await _get_draft_or_raise(db, draft_id)
    if draft.status != DRAFT_STATUS_DRAFT:
        raise DeviceProtocolError(
            f"草稿当前状态 {draft.status}，不可删除（仅 draft 态可删）"
        )
    await db.delete(draft)
    await db.commit()


async def run_draft_check(
    db: AsyncSession, draft_id: int
) -> Dict[str, Any]:
    draft = await _get_draft_or_raise(db, draft_id)
    handler = get_family_handler(draft.protocol_family)
    validation = handler.validate_spec(draft.spec_json or {})
    return {
        "draft_id": draft.id,
        "protocol_family": draft.protocol_family,
        "validation": validation.to_dict(),
        "summary": handler.summarize_spec(draft.spec_json or {}),
    }


async def compute_draft_diff(
    db: AsyncSession, draft_id: int
) -> Dict[str, Any]:
    draft = await _get_draft_or_raise(db, draft_id)
    handler = get_family_handler(draft.protocol_family)
    old_json: Optional[Dict[str, Any]] = None
    if draft.base_version_id:
        base = await get_version(db, draft.base_version_id)
        if base:
            old_json = base.spec_json or {}
    diff = handler.diff_spec(old_json, draft.spec_json or {})
    return diff.to_dict()


# ═════════════════════════ DraftKindHandler 实现 + 审批 ═════════════════════════


class DeviceDraftHandler:
    """把 DeviceProtocolDraft 接入通用 ChangeRequestEngine"""

    def __init__(self, family: str):
        _ensure_family_supported(family)
        self.family = family
        self.kind = draft_kind_for_family(family)
        self._family_handler: FamilyHandler = get_family_handler(family)
        self._git: GitExporter = get_git_exporter()

    async def load_draft(self, db: AsyncSession, draft_id: int) -> DeviceProtocolDraft:
        draft = await _get_draft_or_raise(db, draft_id)
        if draft.protocol_family != self.family:
            raise DeviceProtocolError(
                f"草稿所属协议族 {draft.protocol_family} 与 handler family {self.family} 不一致"
            )
        return draft

    def assert_editable(self, draft: DeviceProtocolDraft) -> None:
        if draft.status != DRAFT_STATUS_DRAFT:
            raise EnginePublishError(
                f"草稿当前状态 {draft.status}，不可提交（仅 draft 态可提交）"
            )

    async def pre_submit_check(
        self, db: AsyncSession, draft: DeviceProtocolDraft
    ) -> None:
        validation = self._family_handler.validate_spec(draft.spec_json or {})
        if not validation.is_ok:
            raise EnginePublishError(
                "静态检查存在 error，未通过：" + "；".join(validation.errors[:5])
            )

    async def ensure_no_concurrent_pending(
        self, db: AsyncSession, draft: DeviceProtocolDraft
    ) -> None:
        """一次 draft = 一个设备 = 一次审批：
        - 对已有 spec：同一 spec 下不允许有另一条 draft/pending；
        - 对新建设备：同一候选 device_id 下不允许有另一条 draft/pending。
        """
        if draft.spec_id is None:
            meta = draft.pending_spec_meta or {}
            other_device_id = meta.get("device_id")
            if not other_device_id:
                return
            res = await db.execute(
                select(DeviceProtocolDraft)
                .where(DeviceProtocolDraft.protocol_family == self.family)
                .where(
                    DeviceProtocolDraft.status.in_(
                        (DRAFT_STATUS_DRAFT, DRAFT_STATUS_PENDING)
                    )
                )
                .where(DeviceProtocolDraft.id != draft.id)
            )
            for other in res.scalars().all():
                other_meta = other.pending_spec_meta or {}
                if other_meta.get("device_id") == other_device_id:
                    raise EnginePublishError(
                        "同一新设备已有另一条活动草稿，请先提交/驳回/删除后再新建"
                    )
            return

        res = await db.execute(
            select(DeviceProtocolDraft)
            .where(DeviceProtocolDraft.spec_id == draft.spec_id)
            .where(
                DeviceProtocolDraft.status.in_(
                    (DRAFT_STATUS_DRAFT, DRAFT_STATUS_PENDING)
                )
            )
            .where(DeviceProtocolDraft.id != draft.id)
        )
        if res.scalar_one_or_none():
            raise EnginePublishError(
                "该设备已有另一条活动草稿（一次修改一个设备走一次审批）"
            )

    async def compute_diff(
        self, db: AsyncSession, draft: DeviceProtocolDraft
    ) -> Dict[str, Any]:
        old_json: Optional[Dict[str, Any]] = None
        if draft.base_version_id:
            base = await get_version(db, draft.base_version_id)
            if base:
                old_json = base.spec_json or {}
        diff = self._family_handler.diff_spec(old_json, draft.spec_json or {})
        return diff.to_dict()

    async def publish(
        self,
        db: AsyncSession,
        draft: DeviceProtocolDraft,
        *,
        admin_username: str,
    ) -> PublishedOutcome:
        # 1) 若是新设备场景：先建 Spec
        spec: DeviceProtocolSpec
        if draft.spec_id is None:
            meta = draft.pending_spec_meta or {}
            if not meta.get("device_id") or not meta.get("device_name"):
                raise EnginePublishError(
                    "新建设备场景下 pending_spec_meta 必须包含 device_id / device_name"
                )
            spec = DeviceProtocolSpec(
                protocol_family=self.family,
                device_id=meta["device_id"],
                device_name=meta["device_name"],
                ata_code=meta.get("ata_code"),
                parent_path=meta.get("parent_path"),
                description=draft.description,
                status=DEVICE_SPEC_ACTIVE,
                created_by=draft.created_by,
            )
            db.add(spec)
            await db.flush()
            draft.spec_id = spec.id
        else:
            spec_loaded = await get_spec_by_id(db, draft.spec_id, with_versions=False)
            if not spec_loaded:
                raise EnginePublishError(f"设备 spec_id={draft.spec_id} 已不存在")
            spec = spec_loaded

        # 2) 自动计算版本号：优先用 draft.target_version（兼容老数据），否则按
        #    spec 当前最大版本号主版本+1（V1.0 → V2.0）。对新建设备从 V1.0 开始。
        if draft.target_version:
            target_version_name = draft.target_version
        else:
            target_version_name = await compute_next_version_name(
                db, spec.id, fallback="V1.0"
            )

        # 版本号唯一性兜底（极少情况下用户历史数据混乱）
        conflict = await db.execute(
            select(DeviceProtocolVersion).where(
                DeviceProtocolVersion.spec_id == spec.id,
                DeviceProtocolVersion.version_name == target_version_name,
            )
        )
        while conflict.scalar_one_or_none():
            target_version_name = increment_major_version(target_version_name)
            conflict = await db.execute(
                select(DeviceProtocolVersion).where(
                    DeviceProtocolVersion.spec_id == spec.id,
                    DeviceProtocolVersion.version_name == target_version_name,
                )
            )

        # 3) 计算 version_seq
        max_seq_res = await db.execute(
            select(func.max(DeviceProtocolVersion.version_seq)).where(
                DeviceProtocolVersion.spec_id == spec.id
            )
        )
        max_seq = max_seq_res.scalar() or 0
        version_seq = int(max_seq) + 1

        # 同步把 spec_json.protocol_meta.version 也更新为最终版本号，便于 Git 副本可读
        normalized_spec = self._family_handler.normalize_spec(draft.spec_json or {})
        normalized_spec.setdefault("protocol_meta", {})
        normalized_spec["protocol_meta"]["version"] = target_version_name

        # 4) 物化 Version（PendingCode）
        version = DeviceProtocolVersion(
            spec_id=spec.id,
            version_name=target_version_name,
            version_seq=version_seq,
            description=(draft.description or "")
            + f"\n[由设备协议草稿 #{draft.id} 发布 → {target_version_name}，admin={admin_username}]",
            spec_json=normalized_spec,
            availability_status=AVAILABILITY_PENDING_CODE,
            git_export_status=GIT_EXPORT_PENDING,
            published_from_draft_id=draft.id,
            created_by=admin_username,
        )
        db.add(version)
        await db.flush()
        # 把最终版本号回写到 draft，方便展示
        draft.target_version = target_version_name

        # 5) Git 审计导出（失败不阻塞）
        try:
            result: ExportResult = await self._git.export_version(
                protocol_family=self.family,
                ata_code=spec.ata_code,
                device_id=spec.device_id,
                device_name=spec.device_name,
                version_name=version.version_name,
                spec_json=version.spec_json,
                commit_message=(
                    f"[{self.family}] {spec.device_id} publish {version.version_name} "
                    f"by {admin_username}"
                ),
                author=admin_username,
            )
            if result.status == "exported":
                version.git_export_status = GIT_EXPORT_EXPORTED
                version.git_commit_hash = result.commit_hash
                version.git_tag = result.tag
                version.git_exported_at = datetime.utcnow()
            elif result.status == "skipped":
                version.git_export_status = GIT_EXPORT_SKIPPED
                version.git_exported_at = datetime.utcnow()
            else:
                version.git_export_status = GIT_EXPORT_FAILED
                version.git_export_error = result.error or "unknown"
                version.git_exported_at = datetime.utcnow()
        except Exception as exc:  # noqa: BLE001
            version.git_export_status = GIT_EXPORT_FAILED
            version.git_export_error = str(exc)[:500]
            version.git_exported_at = datetime.utcnow()

        await db.flush()
        return PublishedOutcome(
            version_id=version.id,
            display_version=f"{spec.device_id} {version.version_name}",
            extra={
                "spec_id": spec.id,
                "git_export_status": version.git_export_status,
            },
        )

    def draft_label(self, draft: DeviceProtocolDraft) -> str:
        if draft.target_version:
            label = f"{self.family.upper()} / {draft.name} → {draft.target_version}"
        else:
            label = f"{self.family.upper()} / {draft.name}"
        if draft.spec_id:
            return label
        meta = draft.pending_spec_meta or {}
        return label + f"（新设备：{meta.get('device_id')}）"

    def cr_link(self, cr_id: int) -> str:
        return f"/device-protocol/change-requests/{cr_id}"

    def attach_draft_to_cr(
        self, cr: ProtocolChangeRequest, draft: DeviceProtocolDraft
    ) -> None:
        cr.device_draft_id = draft.id


async def submit_draft(
    db: AsyncSession,
    draft_id: int,
    *,
    submitter_username: str,
    submitter_role: str,
    note: Optional[str] = None,
) -> ProtocolChangeRequest:
    draft = await _get_draft_or_raise(db, draft_id)
    handler = DeviceDraftHandler(draft.protocol_family)
    engine = ChangeRequestEngine(db, handler)
    try:
        return await engine.submit_draft(
            draft_id,
            submitter_username=submitter_username,
            submitter_role=submitter_role,
            note=note,
        )
    except EnginePublishError as e:
        raise DeviceProtocolError(str(e))


async def _get_cr_or_raise(
    db: AsyncSession, cr_id: int
) -> ProtocolChangeRequest:
    res = await db.execute(
        select(ProtocolChangeRequest)
        .where(ProtocolChangeRequest.id == cr_id)
        .options(
            selectinload(ProtocolChangeRequest.approvals),
            selectinload(ProtocolChangeRequest.device_draft),
            selectinload(ProtocolChangeRequest.draft),
        )
    )
    cr = res.scalar_one_or_none()
    if not cr:
        raise DeviceProtocolError(f"审批流 {cr_id} 不存在")
    return cr


async def sign_off_cr(
    db: AsyncSession,
    cr_id: int,
    *,
    decision: str,
    note: Optional[str],
    user_username: str,
    user_role: str,
) -> ProtocolChangeRequest:
    cr = await _get_cr_or_raise(db, cr_id)
    if cr.device_draft_id is None:
        raise DeviceProtocolError("该审批流不是设备协议类型，请走 /network-config 路径")
    draft = cr.device_draft
    handler = DeviceDraftHandler(draft.protocol_family)
    engine = ChangeRequestEngine(db, handler)
    try:
        return await engine.sign_off_cr(
            cr,
            draft,
            decision=decision,
            note=note,
            user_username=user_username,
            user_role=user_role,
        )
    except EnginePublishError as e:
        raise DeviceProtocolError(str(e))


async def publish_cr(
    db: AsyncSession,
    cr_id: int,
    *,
    admin_username: str,
    admin_role: str,
) -> Dict[str, Any]:
    cr = await _get_cr_or_raise(db, cr_id)
    if cr.device_draft_id is None:
        raise DeviceProtocolError("该审批流不是设备协议类型，请走 /network-config 路径")
    draft = cr.device_draft
    handler = DeviceDraftHandler(draft.protocol_family)
    engine = ChangeRequestEngine(db, handler)
    try:
        outcome = await engine.publish_cr(
            cr,
            draft,
            admin_username=admin_username,
            admin_role=admin_role,
        )
    except EnginePublishError as e:
        raise DeviceProtocolError(str(e))
    return {
        "status": "published",
        "version_id": outcome.version_id,
        "display_version": outcome.display_version,
        "extra": outcome.extra,
    }


async def list_change_requests(
    db: AsyncSession,
    *,
    scope: str = "all",
    family: Optional[str] = None,
    user_username: str,
    user_role: str,
) -> List[ProtocolChangeRequest]:
    stmt = (
        select(ProtocolChangeRequest)
        .where(ProtocolChangeRequest.device_draft_id.isnot(None))
        .options(
            selectinload(ProtocolChangeRequest.approvals),
            selectinload(ProtocolChangeRequest.device_draft),
        )
        .order_by(ProtocolChangeRequest.submitted_at.desc())
    )
    res = await db.execute(stmt)
    items = list(res.scalars().all())
    if family:
        items = [cr for cr in items if (cr.device_draft and cr.device_draft.protocol_family == family)]
    return ChangeRequestEngine.filter_scope(
        items,
        scope=scope,
        user_username=user_username,
        user_role=user_role,
    )


def serialize_cr(cr: ProtocolChangeRequest) -> Dict[str, Any]:
    chain = get_chain_for_kind(cr.draft_kind)
    base: Dict[str, Any] = {
        "id": cr.id,
        "draft_kind": cr.draft_kind,
        "device_draft_id": cr.device_draft_id,
        "submitted_by": cr.submitted_by,
        "submitted_at": cr.submitted_at,
        "current_step": cr.current_step,
        "overall_status": cr.overall_status,
        "final_note": cr.final_note,
        "diff_summary": cr.diff_summary,
        "chain": [
            {
                "step_index": a.step_index,
                "role": a.role,
                "decision": a.decision,
                "approver": a.approver,
                "decided_at": a.decided_at,
                "note": a.note,
            }
            for a in sorted(cr.approvals, key=lambda x: x.step_index)
        ],
        "chain_roles": chain,
    }
    draft = cr.device_draft
    if draft:
        base["device_draft"] = {
            "id": draft.id,
            "spec_id": draft.spec_id,
            "protocol_family": draft.protocol_family,
            "name": draft.name,
            "target_version": draft.target_version,
            "status": draft.status,
            "source_type": draft.source_type,
            "base_version_id": draft.base_version_id,
            "pending_spec_meta": draft.pending_spec_meta,
        }
    return base
