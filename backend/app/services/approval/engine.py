# -*- coding: utf-8 -*-
"""通用审批引擎（ChangeRequestEngine）

抽象目标：
- 输入抽象「草稿对象」和一个 ``DraftKindHandler``；引擎负责通用 3 个动作：
  - ``submit_draft``：静态检查 → 生成 diff → 建 CR + 各步审批位 → 通知下一位
  - ``sign_off_cr``：校验当前 step 角色 → 更新决策 → 推进 or 驳回 → 通知
  - ``publish_cr``：admin 终审物化为一个「已发布版本」对象（由 handler 定义）
- 审批链按 ``draft_kind`` 从 ``approval_policy.get_chain_for_kind`` 取得。
- 通知内容由 handler 通过 ``label`` / ``cr_link`` 给出，保持与业务语义一致。

该引擎先给「设备协议」使用；TSN 路径保持 ``protocol_publish_service`` 不变。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ..notification_service import notify_users_by_role, notify_usernames
from ...approval_policy import get_chain_for_kind, role_can_sign_off
from ...models import (
    APPROVAL_APPROVE,
    APPROVAL_PENDING,
    APPROVAL_REJECT,
    APPROVAL_REQUEST_CHANGES,
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
    NOTIFICATION_KIND_CR_APPROVED,
    NOTIFICATION_KIND_CR_PENDING,
    NOTIFICATION_KIND_CR_PUBLISHED,
    NOTIFICATION_KIND_CR_REJECTED,
    ProtocolChangeRequest,
)
from ...permissions import ROLE_ADMIN, ROLE_DEV_TSN


class EnginePublishError(Exception):
    pass


@dataclass
class PublishedOutcome:
    """publish 完成后 handler 返回的最小结构"""
    version_id: int
    display_version: str
    extra: Dict[str, Any]


class DraftKindHandler(Protocol):
    """不同 draft_kind 需要提供的钩子"""

    kind: str  # 例如 "device_arinc429"

    async def load_draft(self, db: AsyncSession, draft_id: int) -> Any:
        ...

    def assert_editable(self, draft: Any) -> None:
        """draft 可否进入 submit / 是否已被改过的守卫，不满足抛 EnginePublishError"""
        ...

    async def pre_submit_check(self, db: AsyncSession, draft: Any) -> None:
        """静态检查（如字段合法性）；不通过抛 EnginePublishError"""
        ...

    async def ensure_no_concurrent_pending(
        self, db: AsyncSession, draft: Any
    ) -> None:
        """并发锁：同一发布目标上不能有另一个 pending CR"""
        ...

    async def compute_diff(self, db: AsyncSession, draft: Any) -> Dict[str, Any]:
        ...

    async def publish(
        self,
        db: AsyncSession,
        draft: Any,
        *,
        admin_username: str,
    ) -> PublishedOutcome:
        """admin 终审后物化为一个「已发布版本」。应在本方法内置好 DB 对象并 flush；
        commit 由引擎统一处理。"""
        ...

    # 通知辅助
    def draft_label(self, draft: Any) -> str:
        ...

    def cr_link(self, cr_id: int) -> str:
        ...

    # CR 与 draft 的挂接方式（draft_id 或 device_draft_id）
    def attach_draft_to_cr(self, cr: ProtocolChangeRequest, draft: Any) -> None:
        ...


class ChangeRequestEngine:
    def __init__(self, db: AsyncSession, handler: DraftKindHandler):
        self.db = db
        self.handler = handler

    # ──────────────── submit ────────────────
    async def submit_draft(
        self,
        draft_id: int,
        *,
        submitter_username: str,
        submitter_role: str,
        note: Optional[str] = None,
    ) -> ProtocolChangeRequest:
        draft = await self.handler.load_draft(self.db, draft_id)
        if getattr(draft, "status", None) != DRAFT_STATUS_DRAFT:
            raise EnginePublishError(
                f"草稿当前状态 {getattr(draft, 'status', None)}，只能在 draft 态提交"
            )

        self.handler.assert_editable(draft)
        await self.handler.pre_submit_check(self.db, draft)
        await self.handler.ensure_no_concurrent_pending(self.db, draft)

        diff = await self.handler.compute_diff(self.db, draft)

        chain = get_chain_for_kind(self.handler.kind)

        cr = ProtocolChangeRequest(
            draft_kind=self.handler.kind,
            submitted_by=submitter_username,
            submitted_at=datetime.utcnow(),
            current_step=1,  # step0 = 提交者自身
            overall_status=CR_STATUS_PENDING,
            diff_summary=diff,
        )
        self.handler.attach_draft_to_cr(cr, draft)
        self.db.add(cr)
        await self.db.flush()

        for idx, role in enumerate(chain):
            if idx == 0:
                self.db.add(
                    ChangeRequestApproval(
                        cr_id=cr.id,
                        role=role,
                        step_index=idx,
                        decision=APPROVAL_APPROVE,
                        approver=submitter_username,
                        decided_at=datetime.utcnow(),
                        note=note,
                    )
                )
            else:
                self.db.add(
                    ChangeRequestApproval(
                        cr_id=cr.id,
                        role=role,
                        step_index=idx,
                        decision=APPROVAL_PENDING,
                    )
                )

        draft.status = DRAFT_STATUS_PENDING
        draft.submit_note = note
        draft.updated_at = datetime.utcnow()

        # 推送下一位
        if cr.current_step < len(chain):
            next_role = chain[cr.current_step]
            await notify_users_by_role(
                self.db,
                role=next_role,
                kind=NOTIFICATION_KIND_CR_PENDING,
                title=f"有新的协议变更待您会签：{self.handler.draft_label(draft)}",
                body=f"提交人 {submitter_username}；审批链 {' → '.join(chain)}",
                link=self.handler.cr_link(cr.id),
            )

        await self.db.commit()
        return cr

    # ──────────────── sign_off ────────────────
    async def sign_off_cr(
        self,
        cr: ProtocolChangeRequest,
        draft: Any,
        *,
        decision: str,
        note: Optional[str],
        user_username: str,
        user_role: str,
    ) -> ProtocolChangeRequest:
        if decision not in {APPROVAL_APPROVE, APPROVAL_REJECT, APPROVAL_REQUEST_CHANGES}:
            raise EnginePublishError(f"decision 非法：{decision}")
        if cr.overall_status != CR_STATUS_PENDING:
            raise EnginePublishError(
                f"审批流当前状态 {cr.overall_status}，不可会签"
            )

        chain = get_chain_for_kind(cr.draft_kind)
        if cr.current_step >= len(chain):
            raise EnginePublishError("审批链已走完，无需再会签")

        step_role = chain[cr.current_step]
        if not role_can_sign_off(user_role, step_role):
            raise EnginePublishError(
                f"当前步骤需要 {step_role} 角色，当前用户角色 {user_role} 不匹配"
            )

        approval = next(
            (a for a in cr.approvals if a.step_index == cr.current_step), None
        )
        if approval is None:
            raise EnginePublishError("审批位未初始化")
        approval.decision = decision
        approval.approver = user_username
        approval.decided_at = datetime.utcnow()
        approval.note = note

        if decision == APPROVAL_APPROVE:
            cr.current_step += 1
            if cr.current_step >= len(chain):
                cr.overall_status = CR_STATUS_APPROVED
                draft.status = DRAFT_STATUS_APPROVED
            else:
                next_role = chain[cr.current_step]
                await notify_users_by_role(
                    self.db,
                    role=next_role,
                    kind=NOTIFICATION_KIND_CR_PENDING,
                    title=f"协议变更待您会签：{self.handler.draft_label(draft)}",
                    body=f"来自 {user_username}（{step_role}）已通过",
                    link=self.handler.cr_link(cr.id),
                )
                await notify_usernames(
                    self.db,
                    usernames=[cr.submitted_by] if cr.submitted_by else [],
                    kind=NOTIFICATION_KIND_CR_APPROVED,
                    title=f"您的协议变更已被 {step_role} 会签通过",
                    body=f"当前推进至：{next_role}",
                    link=self.handler.cr_link(cr.id),
                )
        else:
            cr.overall_status = CR_STATUS_REJECTED
            cr.final_note = note
            draft.status = (
                DRAFT_STATUS_REJECTED
                if decision == APPROVAL_REJECT
                else DRAFT_STATUS_DRAFT
            )
            await notify_usernames(
                self.db,
                usernames=[cr.submitted_by] if cr.submitted_by else [],
                kind=NOTIFICATION_KIND_CR_REJECTED,
                title=f"您的协议变更被 {step_role} {decision}",
                body=note or "",
                link=self.handler.cr_link(cr.id),
            )

        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        return cr

    # ──────────────── publish ────────────────
    async def publish_cr(
        self,
        cr: ProtocolChangeRequest,
        draft: Any,
        *,
        admin_username: str,
        admin_role: str,
    ) -> PublishedOutcome:
        if admin_role != ROLE_ADMIN:
            raise EnginePublishError("仅管理员可发布")
        if cr.overall_status != CR_STATUS_APPROVED:
            raise EnginePublishError(
                f"审批流当前状态 {cr.overall_status}，仅 approved 状态可发布"
            )
        if draft.status != DRAFT_STATUS_APPROVED:
            raise EnginePublishError(
                f"草稿当前状态 {draft.status}，无法发布"
            )

        outcome = await self.handler.publish(
            self.db, draft, admin_username=admin_username
        )

        cr.overall_status = CR_STATUS_PUBLISHED
        cr.final_note = f"由 {admin_username} 发布"
        draft.status = DRAFT_STATUS_PUBLISHED
        draft.published_version_id = outcome.version_id
        draft.updated_at = datetime.utcnow()

        await notify_usernames(
            self.db,
            usernames=[cr.submitted_by] if cr.submitted_by else [],
            kind=NOTIFICATION_KIND_CR_PUBLISHED,
            title=f"协议变更已发布：{self.handler.draft_label(draft)}",
            body=f"新版本 {outcome.display_version} 已登记为 PendingCode，待代码就绪后由管理员激活",
            link=self.handler.cr_link(cr.id),
        )
        await notify_users_by_role(
            self.db,
            role=ROLE_DEV_TSN,
            kind=NOTIFICATION_KIND_CR_PUBLISHED,
            title=f"设备协议新版本登记为 PendingCode：{self.handler.draft_label(draft)}",
            body=f"请同步后端解析代码；版本 {outcome.display_version}",
            link=self.handler.cr_link(cr.id),
        )

        await self.db.commit()
        return outcome

    # ──────────────── list ────────────────
    @staticmethod
    def filter_scope(
        items: List[ProtocolChangeRequest],
        *,
        scope: str,
        user_username: str,
        user_role: str,
        kind_filter: Optional[str] = None,
    ) -> List[ProtocolChangeRequest]:
        def _keep(cr: ProtocolChangeRequest) -> bool:
            if kind_filter and cr.draft_kind != kind_filter:
                return False
            if scope == "mine":
                return cr.submitted_by == user_username
            if scope == "pending_for_me":
                if cr.overall_status != CR_STATUS_PENDING:
                    return False
                chain = get_chain_for_kind(cr.draft_kind)
                if cr.current_step >= len(chain):
                    return False
                return role_can_sign_off(user_role, chain[cr.current_step])
            return True

        return [cr for cr in items if _keep(cr)]
