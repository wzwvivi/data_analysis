# -*- coding: utf-8 -*-
"""TSN 协议草稿审批 / 发布（MR2）

流程：
  submit   → 静态检查无 error + 建 ChangeRequest + 各审批步 + 通知下一位
  sign_off → 当前 step 对应角色 approve/reject/request_changes
  publish  → 终审 admin 物化为 ProtocolVersion(availability_status=PendingCode)

激活闸门（PendingCode → Available）留给 MR3。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..approval_policy import DEFAULT_APPROVAL_CHAIN, role_can_sign_off
from ..models import (
    APPROVAL_APPROVE,
    APPROVAL_PENDING,
    APPROVAL_REJECT,
    APPROVAL_REQUEST_CHANGES,
    AVAILABILITY_PENDING_CODE,
    ChangeRequestApproval,
    CR_STATUS_APPROVED,
    CR_STATUS_PENDING,
    CR_STATUS_PUBLISHED,
    CR_STATUS_REJECTED,
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_PUBLISHED,
    DRAFT_STATUS_REJECTED,
    DraftFieldDefinition,
    DraftPortDefinition,
    FieldDefinition,
    NOTIFICATION_KIND_CR_APPROVED,
    NOTIFICATION_KIND_CR_PENDING,
    NOTIFICATION_KIND_CR_PUBLISHED,
    NOTIFICATION_KIND_CR_REJECTED,
    PortDefinition,
    Protocol,
    ProtocolChangeRequest,
    ProtocolVersion,
    ProtocolVersionDraft,
)
from ..permissions import ROLE_ADMIN
from .notification_service import notify_users_by_role, notify_usernames
from .protocol_check_service import run_static_check


class PublishError(Exception):
    pass


# ───── 帮助 ─────
async def _get_draft(db: AsyncSession, draft_id: int) -> ProtocolVersionDraft:
    res = await db.execute(
        select(ProtocolVersionDraft)
        .where(ProtocolVersionDraft.id == draft_id)
        .options(
            selectinload(ProtocolVersionDraft.ports).selectinload(
                DraftPortDefinition.fields
            ),
            selectinload(ProtocolVersionDraft.change_requests).selectinload(
                ProtocolChangeRequest.approvals
            ),
        )
    )
    draft = res.scalar_one_or_none()
    if not draft:
        raise PublishError(f"草稿 {draft_id} 不存在")
    return draft


async def _get_cr(db: AsyncSession, cr_id: int) -> ProtocolChangeRequest:
    res = await db.execute(
        select(ProtocolChangeRequest)
        .where(ProtocolChangeRequest.id == cr_id)
        .options(
            selectinload(ProtocolChangeRequest.approvals),
            selectinload(ProtocolChangeRequest.draft).selectinload(
                ProtocolVersionDraft.ports
            ).selectinload(DraftPortDefinition.fields),
        )
    )
    cr = res.scalar_one_or_none()
    if not cr:
        raise PublishError(f"审批流 {cr_id} 不存在")
    return cr


def _cr_link(cr_id: int) -> str:
    return f"/network-config/change-requests/{cr_id}"


# ───── submit ─────
async def submit_draft(
    db: AsyncSession,
    draft_id: int,
    *,
    submitter_username: str,
    submitter_role: str,
    note: Optional[str] = None,
) -> ProtocolChangeRequest:
    draft = await _get_draft(db, draft_id)
    if draft.status != DRAFT_STATUS_DRAFT:
        raise PublishError(f"草稿当前状态 {draft.status}，只能在 draft 态提交")

    # 静态检查必须无 error
    check = await run_static_check(db, draft_id)
    if check["summary"]["error_count"] > 0:
        raise PublishError("静态检查存在 error，未通过，无法提交")

    # 并发锁：同一 base_version 同时只允许一个 pending CR
    if draft.base_version_id is not None:
        res = await db.execute(
            select(ProtocolVersionDraft)
            .where(ProtocolVersionDraft.base_version_id == draft.base_version_id)
            .where(ProtocolVersionDraft.status == DRAFT_STATUS_PENDING)
            .where(ProtocolVersionDraft.id != draft.id)
        )
        if res.scalar_one_or_none():
            raise PublishError("该基础版本上已有另一个审批中的草稿，请先等其完结")

    # 生成 diff 快照
    from .protocol_draft_service import ProtocolDraftService
    diff = await ProtocolDraftService(db).compute_diff(draft_id)

    # 创建 CR（显式标记为 TSN 网络配置，供通用审批引擎区分）
    cr = ProtocolChangeRequest(
        draft_id=draft.id,
        draft_kind="tsn_network",
        submitted_by=submitter_username,
        submitted_at=datetime.utcnow(),
        current_step=1,  # step0 = 提交者本身
        overall_status=CR_STATUS_PENDING,
        diff_summary=diff,
    )
    db.add(cr)
    await db.flush()

    # 建审批位：step0 自动 approve（提交者），其余 pending
    for idx, role in enumerate(DEFAULT_APPROVAL_CHAIN):
        if idx == 0:
            db.add(ChangeRequestApproval(
                cr_id=cr.id,
                role=role,
                step_index=idx,
                decision=APPROVAL_APPROVE,
                approver=submitter_username,
                decided_at=datetime.utcnow(),
                note=note,
            ))
        else:
            db.add(ChangeRequestApproval(
                cr_id=cr.id,
                role=role,
                step_index=idx,
                decision=APPROVAL_PENDING,
            ))

    draft.status = DRAFT_STATUS_PENDING
    draft.submit_note = note
    draft.updated_at = datetime.utcnow()

    # 推送下一位审批人
    next_role = DEFAULT_APPROVAL_CHAIN[cr.current_step]
    await notify_users_by_role(
        db,
        role=next_role,
        kind=NOTIFICATION_KIND_CR_PENDING,
        title=f"有新的 TSN 协议变更待您会签：{draft.name}",
        body=f"草稿 #{draft.id} / 目标版本 {draft.target_version}，提交人 {submitter_username}",
        link=_cr_link(cr.id),
    )

    await db.commit()
    # 重新 eager-load approvals + draft，避免调用方 serialize_cr 触发 lazy-load（MissingGreenlet）
    return await _get_cr(db, cr.id)


# ───── sign off ─────
async def sign_off_cr(
    db: AsyncSession,
    cr_id: int,
    *,
    decision: str,
    note: Optional[str],
    user_username: str,
    user_role: str,
) -> ProtocolChangeRequest:
    if decision not in {APPROVAL_APPROVE, APPROVAL_REJECT, APPROVAL_REQUEST_CHANGES}:
        raise PublishError(f"decision 非法：{decision}")
    cr = await _get_cr(db, cr_id)
    if cr.overall_status != CR_STATUS_PENDING:
        raise PublishError(f"审批流当前状态 {cr.overall_status}，不可会签")

    step_role = DEFAULT_APPROVAL_CHAIN[cr.current_step] if cr.current_step < len(DEFAULT_APPROVAL_CHAIN) else None
    if step_role is None:
        raise PublishError("审批链已走完，无需再会签（应走 publish 流程）")

    if not role_can_sign_off(user_role, step_role):
        raise PublishError(f"当前步骤需要 {step_role} 角色，当前用户角色 {user_role} 不匹配")

    approval = next((a for a in cr.approvals if a.step_index == cr.current_step), None)
    if approval is None:
        raise PublishError("审批位未初始化")
    approval.decision = decision
    approval.approver = user_username
    approval.decided_at = datetime.utcnow()
    approval.note = note

    draft = cr.draft
    if decision == APPROVAL_APPROVE:
        cr.current_step += 1
        # 如果已经到终审并通过，overall_status 标记 approved，等 admin publish
        if cr.current_step >= len(DEFAULT_APPROVAL_CHAIN):
            cr.overall_status = CR_STATUS_APPROVED
            draft.status = DRAFT_STATUS_APPROVED
        else:
            next_role = DEFAULT_APPROVAL_CHAIN[cr.current_step]
            await notify_users_by_role(
                db,
                role=next_role,
                kind=NOTIFICATION_KIND_CR_PENDING,
                title=f"TSN 协议变更待您会签：{draft.name}",
                body=f"来自 {user_username}（{step_role}）已通过",
                link=_cr_link(cr.id),
            )
            await notify_usernames(
                db,
                usernames=[cr.submitted_by] if cr.submitted_by else [],
                kind=NOTIFICATION_KIND_CR_APPROVED,
                title=f"您的 TSN 协议变更已被 {step_role} 会签通过",
                body=f"当前推进至：{DEFAULT_APPROVAL_CHAIN[cr.current_step]}",
                link=_cr_link(cr.id),
            )
    else:
        # reject / request_changes：整体驳回
        cr.overall_status = CR_STATUS_REJECTED
        cr.final_note = note
        draft.status = DRAFT_STATUS_REJECTED if decision == APPROVAL_REJECT else DRAFT_STATUS_DRAFT
        await notify_usernames(
            db,
            usernames=[cr.submitted_by] if cr.submitted_by else [],
            kind=NOTIFICATION_KIND_CR_REJECTED,
            title=f"您的 TSN 协议变更被 {step_role} {decision}",
            body=note or "",
            link=_cr_link(cr.id),
        )

    draft.updated_at = datetime.utcnow()
    await db.commit()
    return await _get_cr(db, cr.id)


# ───── publish ─────
async def publish_cr(
    db: AsyncSession,
    cr_id: int,
    *,
    admin_username: str,
    admin_role: str,
) -> ProtocolVersion:
    if admin_role != ROLE_ADMIN:
        raise PublishError("仅管理员可发布")
    cr = await _get_cr(db, cr_id)
    if cr.overall_status != CR_STATUS_APPROVED:
        raise PublishError(
            f"审批流当前状态 {cr.overall_status}，仅 approved 状态可发布"
        )
    draft = cr.draft
    if draft.status != DRAFT_STATUS_APPROVED:
        raise PublishError(f"草稿当前状态 {draft.status}，无法发布")

    # 物化：建 ProtocolVersion(availability_status=PendingCode) 并深拷贝端口/字段
    pv = ProtocolVersion(
        protocol_id=draft.protocol_id,
        version=draft.target_version,
        source_file=f"draft#{draft.id}",
        description=(draft.description or "") + f"\n[由 CR#{cr.id} 发布]",
        availability_status=AVAILABILITY_PENDING_CODE,
    )
    db.add(pv)
    await db.flush()

    from .protocol_draft_service import PORT_MUTABLE_ATTRS
    for dp in draft.ports or []:
        port = PortDefinition(
            protocol_version_id=pv.id,
            port_number=dp.port_number,
            **{attr: getattr(dp, attr, None) for attr in PORT_MUTABLE_ATTRS},
        )
        db.add(port)
        await db.flush()
        for df_ in dp.fields or []:
            db.add(
                FieldDefinition(
                    port_id=port.id,
                    field_name=df_.field_name,
                    field_offset=df_.field_offset,
                    field_length=df_.field_length,
                    data_type=df_.data_type,
                    scale_factor=df_.scale_factor,
                    unit=df_.unit,
                    description=df_.description,
                    byte_order=df_.byte_order,
                )
            )

    cr.overall_status = CR_STATUS_PUBLISHED
    cr.final_note = f"由 {admin_username} 发布"
    draft.status = DRAFT_STATUS_PUBLISHED
    draft.published_version_id = pv.id
    draft.updated_at = datetime.utcnow()

    # 通知提交者 + admin + TSN 开发团队（代码就绪由他们闭环）
    from ..permissions import ROLE_DEV_TSN
    await notify_usernames(
        db,
        usernames=[cr.submitted_by] if cr.submitted_by else [],
        kind=NOTIFICATION_KIND_CR_PUBLISHED,
        title=f"TSN 协议变更已发布（PendingCode）：{draft.name}",
        body=f"新版本 v{draft.target_version} 已登记为 PendingCode，待代码就绪后由管理员激活",
        link=_cr_link(cr.id),
    )
    await notify_users_by_role(
        db,
        role=ROLE_DEV_TSN,
        kind=NOTIFICATION_KIND_CR_PUBLISHED,
        title=f"TSN 协议新版本登记为 PendingCode：{draft.name}",
        body=f"请确认后端解析是否需要同步；版本号 v{draft.target_version}",
        link=_cr_link(cr.id),
    )

    await db.commit()
    await db.refresh(pv)
    return pv


# ───── 查询 ─────
async def list_change_requests(
    db: AsyncSession,
    *,
    scope: str,
    user_username: str,
    user_role: str,
) -> List[Dict[str, Any]]:
    stmt = (
        select(ProtocolChangeRequest)
        .options(
            selectinload(ProtocolChangeRequest.approvals),
            selectinload(ProtocolChangeRequest.draft),
        )
        .order_by(ProtocolChangeRequest.submitted_at.desc())
    )
    res = await db.execute(stmt)
    items = list(res.scalars().all())

    def _keep(cr: ProtocolChangeRequest) -> bool:
        if scope == "mine":
            return cr.submitted_by == user_username
        if scope == "pending_for_me":
            if cr.overall_status != CR_STATUS_PENDING:
                return False
            if cr.current_step >= len(DEFAULT_APPROVAL_CHAIN):
                return False
            step_role = DEFAULT_APPROVAL_CHAIN[cr.current_step]
            return role_can_sign_off(user_role, step_role)
        return True

    filtered = [cr for cr in items if _keep(cr)]
    return filtered


def serialize_cr(cr: ProtocolChangeRequest) -> Dict[str, Any]:
    return {
        "id": cr.id,
        "draft_id": cr.draft_id,
        "submitted_by": cr.submitted_by,
        "submitted_at": cr.submitted_at,
        "current_step": cr.current_step,
        "overall_status": cr.overall_status,
        "final_note": cr.final_note,
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
        "diff_summary": cr.diff_summary,
        "draft": {
            "id": cr.draft.id,
            "name": cr.draft.name,
            "target_version": cr.draft.target_version,
            "status": cr.draft.status,
            "source_type": cr.draft.source_type,
            "base_version_id": cr.draft.base_version_id,
            "protocol_id": cr.draft.protocol_id,
        } if cr.draft else None,
    }
