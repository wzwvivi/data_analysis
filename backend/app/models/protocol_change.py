# -*- coding: utf-8 -*-
"""TSN 协议草稿与审批相关模型（MR2）

Draft 与正式 ProtocolVersion 完全隔离：编辑/审批只动 draft 表，publish 后
才把 draft 物化为 ProtocolVersion(availability_status='PendingCode')；老版本及其
历史解析任务全程不受影响。
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from ..database import Base


# ── Draft 状态常量 ──
DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_PENDING = "pending"
DRAFT_STATUS_REJECTED = "rejected"
DRAFT_STATUS_APPROVED = "approved"
DRAFT_STATUS_PUBLISHED = "published"
DRAFT_STATUSES = (
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_PENDING,
    DRAFT_STATUS_REJECTED,
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_PUBLISHED,
)

DRAFT_SOURCE_CLONE = "clone"
DRAFT_SOURCE_EXCEL = "excel"
DRAFT_SOURCES = (DRAFT_SOURCE_CLONE, DRAFT_SOURCE_EXCEL)

# ── 审批决策常量 ──
APPROVAL_PENDING = "pending"
APPROVAL_APPROVE = "approve"
APPROVAL_REJECT = "reject"
APPROVAL_REQUEST_CHANGES = "request_changes"
APPROVAL_DECISIONS = (
    APPROVAL_PENDING,
    APPROVAL_APPROVE,
    APPROVAL_REJECT,
    APPROVAL_REQUEST_CHANGES,
)

CR_STATUS_PENDING = "pending"
CR_STATUS_REJECTED = "rejected"
CR_STATUS_APPROVED = "approved"
CR_STATUS_PUBLISHED = "published"
CR_STATUSES = (
    CR_STATUS_PENDING,
    CR_STATUS_REJECTED,
    CR_STATUS_APPROVED,
    CR_STATUS_PUBLISHED,
)

# ── 通知类型 ──
NOTIFICATION_KIND_CR_PENDING = "cr_pending_signoff"
NOTIFICATION_KIND_CR_APPROVED = "cr_approved"
NOTIFICATION_KIND_CR_REJECTED = "cr_rejected"
NOTIFICATION_KIND_CR_PUBLISHED = "cr_published"
NOTIFICATION_KIND_DRAFT_CHECK_FAILED = "draft_check_failed"


class ProtocolVersionDraft(Base):
    """协议版本草稿（写操作只在这里发生）"""
    __tablename__ = "protocol_version_drafts"

    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(Integer, ForeignKey("protocols.id"), nullable=False)
    # clone 场景必填，excel 新架次为空
    base_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=True)
    source_type = Column(String(20), nullable=False, comment="clone | excel")

    name = Column(String(200), nullable=False, comment="人类可读草稿标题")
    target_version = Column(String(50), nullable=False, comment="打算发布的新版本号")
    description = Column(Text, nullable=True)
    source_file_path = Column(String(500), nullable=True, comment="Excel 本地落盘路径（若有）")

    status = Column(
        String(20),
        nullable=False,
        default=DRAFT_STATUS_DRAFT,
        comment="draft | pending | rejected | approved | published",
    )
    submit_note = Column(Text, nullable=True)

    created_by = Column(String(64), nullable=True, comment="创建者用户名")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    published_version_id = Column(
        Integer, ForeignKey("protocol_versions.id"), nullable=True,
        comment="publish 后写入，指向新 ProtocolVersion",
    )

    ports = relationship(
        "DraftPortDefinition",
        back_populates="draft",
        cascade="all, delete-orphan",
    )
    change_requests = relationship(
        "ProtocolChangeRequest",
        back_populates="draft",
        cascade="all, delete-orphan",
    )


class DraftPortDefinition(Base):
    """Draft 端口（镜像 PortDefinition）"""
    __tablename__ = "draft_port_definitions"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(Integer, ForeignKey("protocol_version_drafts.id"), nullable=False, index=True)

    port_number = Column(Integer, nullable=False)
    message_name = Column(String(100))
    source_device = Column(String(100))
    target_device = Column(String(100))
    multicast_ip = Column(String(50))
    data_direction = Column(String(20), comment="uplink | downlink | network")
    period_ms = Column(Float)
    description = Column(Text)
    protocol_family = Column(String(50), nullable=True)
    port_role = Column(String(50), nullable=True, comment="端口业务角色（与正式表对齐）")

    # ── ICD 6.0.x 原表头映射（扩展列） ──
    message_id = Column(String(64), nullable=True)
    source_interface_id = Column(String(64), nullable=True)
    port_id_label = Column(String(64), nullable=True)
    diu_id = Column(String(64), nullable=True)
    diu_id_set = Column(String(200), nullable=True)
    diu_recv_mode = Column(String(100), nullable=True)
    tsn_source_ip = Column(String(100), nullable=True)
    diu_ip = Column(String(100), nullable=True)
    dataset_path = Column(String(200), nullable=True)
    data_real_path = Column(String(200), nullable=True)
    final_recv_device = Column(String(100), nullable=True)

    draft = relationship("ProtocolVersionDraft", back_populates="ports")
    fields = relationship(
        "DraftFieldDefinition",
        back_populates="port",
        cascade="all, delete-orphan",
    )


class DraftFieldDefinition(Base):
    """Draft 字段（镜像 FieldDefinition）"""
    __tablename__ = "draft_field_definitions"

    id = Column(Integer, primary_key=True, index=True)
    draft_port_id = Column(Integer, ForeignKey("draft_port_definitions.id"), nullable=False, index=True)

    field_name = Column(String(100), nullable=False)
    field_offset = Column(Integer, nullable=False)
    field_length = Column(Integer, nullable=False)
    data_type = Column(String(50), default="bytes")
    scale_factor = Column(Float, default=1.0)
    unit = Column(String(50))
    description = Column(Text)
    byte_order = Column(String(10), default="big")

    port = relationship("DraftPortDefinition", back_populates="fields")


class ProtocolChangeRequest(Base):
    """协议变更请求 = 一次审批流

    通过 ``draft_kind`` 区分多种协议类型：
    - ``tsn_network``：TSN 网络配置管理（draft_id → protocol_version_drafts）
    - ``device_arinc429`` / ``device_can`` / ``device_rs422``：设备协议
      （device_draft_id → device_protocol_drafts）
    两个 draft FK 互斥：根据 draft_kind 只读其中一个。
    """
    __tablename__ = "protocol_change_requests"

    id = Column(Integer, primary_key=True, index=True)
    # TSN 网络配置管理草稿（保留兼容；device 场景下为空）
    draft_id = Column(Integer, ForeignKey("protocol_version_drafts.id"), nullable=True, index=True)
    # 设备协议草稿（新）
    device_draft_id = Column(
        Integer,
        ForeignKey("device_protocol_drafts.id"),
        nullable=True,
        index=True,
    )
    draft_kind = Column(
        String(40),
        nullable=False,
        default="tsn_network",
        index=True,
        comment="tsn_network / device_arinc429 / device_can / device_rs422",
    )

    submitted_by = Column(String(64), nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)

    current_step = Column(Integer, nullable=False, default=0, comment="下一步需要决策的链位索引")
    overall_status = Column(
        String(20),
        nullable=False,
        default=CR_STATUS_PENDING,
        comment="pending | rejected | approved | published",
    )
    diff_summary = Column(JSON, nullable=True, comment="submit 时刻生成的 diff 快照")
    final_note = Column(Text, nullable=True, comment="终审 / 驳回 记录")
    # TSN 网络配置管理专用：提交者勾选的"变更激活后需知会的团队"列表
    # 例如 ["fms", "fcc"]；激活 ProtocolVersion 时据此发站内通知，不影响审批链。
    notify_teams = Column(JSON, nullable=True, default=list, comment="激活后知会团队代码列表")

    draft = relationship(
        "ProtocolVersionDraft",
        back_populates="change_requests",
        foreign_keys=[draft_id],
    )
    device_draft = relationship(
        "DeviceProtocolDraft",
        back_populates="change_requests",
        foreign_keys=[device_draft_id],
    )
    approvals = relationship(
        "ChangeRequestApproval",
        back_populates="change_request",
        cascade="all, delete-orphan",
        order_by="ChangeRequestApproval.step_index",
    )


class ChangeRequestApproval(Base):
    """每一步审批位记录"""
    __tablename__ = "change_request_approvals"

    id = Column(Integer, primary_key=True, index=True)
    cr_id = Column(Integer, ForeignKey("protocol_change_requests.id"), nullable=False, index=True)

    role = Column(String(40), nullable=False, comment="该步需要的角色")
    step_index = Column(Integer, nullable=False, comment="在审批链中的序号（0 起）")
    decision = Column(String(20), nullable=False, default=APPROVAL_PENDING)
    approver = Column(String(64), nullable=True, comment="实际操作者用户名")
    decided_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    change_request = relationship("ProtocolChangeRequest", back_populates="approvals")


class Notification(Base):
    """站内通知（最小可用）"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    # 以 username 落库而非 user_id：新建用户不会影响，按 user 名字发送；
    # user_id 如果有也落，便于后续做用户级权限过滤
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(64), nullable=True, index=True)

    kind = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String(500), nullable=True, comment="前端跳转路径")
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
