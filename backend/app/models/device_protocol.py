# -*- coding: utf-8 -*-
"""设备协议（ARINC429 / CAN / RS422 ...）通用模型

与 TSN 网络配置（protocols / protocol_versions / ports / fields）区分；设备协议
以 protocol_family 区分具体家族，每个家族的内部结构差异封装在 spec_json 里，由
family handler 负责 validate/diff/normalize。

版本生命周期对齐 TSN：Available / PendingCode / Deprecated。
审批流程与 TSN 共用 ``ProtocolChangeRequest``，按 ``draft_kind`` 区分。
Git 审计导出（方案 2）仅在 publish 时触发，git_commit_hash 为空表示尚未导出，
git_export_status 取值 pending / exported / skipped / failed。
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..database import Base


# ── 协议族常量（设备协议）──
PROTOCOL_FAMILY_ARINC429 = "arinc429"
PROTOCOL_FAMILY_CAN = "can"
PROTOCOL_FAMILY_RS422 = "rs422"

DEVICE_PROTOCOL_FAMILIES = (
    PROTOCOL_FAMILY_ARINC429,
    PROTOCOL_FAMILY_CAN,
    PROTOCOL_FAMILY_RS422,
)


# ── draft_kind 常量（审批链按 kind 选链）──
DRAFT_KIND_TSN_NETWORK = "tsn_network"
DRAFT_KIND_DEVICE_ARINC429 = "device_arinc429"
DRAFT_KIND_DEVICE_CAN = "device_can"
DRAFT_KIND_DEVICE_RS422 = "device_rs422"

DRAFT_KINDS = (
    DRAFT_KIND_TSN_NETWORK,
    DRAFT_KIND_DEVICE_ARINC429,
    DRAFT_KIND_DEVICE_CAN,
    DRAFT_KIND_DEVICE_RS422,
)


def draft_kind_for_family(family: str) -> str:
    mapping = {
        PROTOCOL_FAMILY_ARINC429: DRAFT_KIND_DEVICE_ARINC429,
        PROTOCOL_FAMILY_CAN: DRAFT_KIND_DEVICE_CAN,
        PROTOCOL_FAMILY_RS422: DRAFT_KIND_DEVICE_RS422,
    }
    return mapping.get(family, DRAFT_KIND_DEVICE_ARINC429)


# ── Git 导出状态 ──
GIT_EXPORT_PENDING = "pending"
GIT_EXPORT_EXPORTED = "exported"
GIT_EXPORT_SKIPPED = "skipped"
GIT_EXPORT_FAILED = "failed"

GIT_EXPORT_STATUSES = (
    GIT_EXPORT_PENDING,
    GIT_EXPORT_EXPORTED,
    GIT_EXPORT_SKIPPED,
    GIT_EXPORT_FAILED,
)


# ── 设备状态 ──
DEVICE_SPEC_ACTIVE = "active"
DEVICE_SPEC_DEPRECATED = "deprecated"


class DeviceProtocolSpec(Base):
    """逻辑设备：挂载在 ATA 系统下，持有多个版本"""

    __tablename__ = "device_protocol_specs"
    __table_args__ = (
        UniqueConstraint(
            "protocol_family",
            "device_id",
            name="uq_device_protocol_family_device_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    protocol_family = Column(
        String(50),
        nullable=False,
        index=True,
        comment="arinc429 / can / rs422 ...",
    )
    ata_code = Column(String(20), nullable=True, index=True, comment="ATA 系统码，如 ata32")
    device_id = Column(
        String(200),
        nullable=False,
        index=True,
        comment="稳定字符串ID，如 ata32_32_3 / can_ivi_main",
    )
    device_name = Column(String(500), nullable=False)
    parent_path = Column(
        JSON,
        nullable=True,
        comment="父级路径，如 ['ATA32', '起落架系统']",
    )
    description = Column(Text, nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default=DEVICE_SPEC_ACTIVE,
        comment="active / deprecated",
    )
    current_version_id = Column(
        Integer,
        ForeignKey("device_protocol_versions.id", use_alter=True, name="fk_spec_current_version"),
        nullable=True,
        comment="当前 Available 版本（冗余指针，便于查询）",
    )

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    versions = relationship(
        "DeviceProtocolVersion",
        back_populates="spec",
        cascade="all, delete-orphan",
        foreign_keys="DeviceProtocolVersion.spec_id",
    )
    drafts = relationship(
        "DeviceProtocolDraft",
        back_populates="spec",
        cascade="all, delete-orphan",
        foreign_keys="DeviceProtocolDraft.spec_id",
    )


class DeviceProtocolVersion(Base):
    """设备协议已发布版本（一次 publish 一条）"""

    __tablename__ = "device_protocol_versions"
    __table_args__ = (
        UniqueConstraint(
            "spec_id", "version_name", name="uq_device_protocol_version_name"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(
        Integer,
        ForeignKey("device_protocol_specs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_name = Column(String(200), nullable=False, comment="人类可读版本号，如 V2.0")
    version_seq = Column(Integer, nullable=False, default=1, comment="序号，用于排序")
    description = Column(Text, nullable=True)
    source_file = Column(String(255), nullable=True, comment="来源文件（Excel 导入等）")

    # 全量规格 JSON；家族 handler 负责 validate/diff
    spec_json = Column(JSON, nullable=False, default=dict)

    availability_status = Column(
        String(20),
        nullable=False,
        default="Available",
        comment="Available / PendingCode / Deprecated（与 TSN 对齐）",
    )
    activated_at = Column(DateTime, nullable=True)
    activated_by = Column(String(64), nullable=True)

    # ── 方案2：Git 审计副本元信息 ──
    git_commit_hash = Column(
        String(64),
        nullable=True,
        comment="publish 时导出到 Git 后回填的 commit hash",
    )
    git_tag = Column(String(200), nullable=True, comment="Git 标签名（可选）")
    git_export_status = Column(
        String(20),
        nullable=False,
        default=GIT_EXPORT_PENDING,
        comment="pending / exported / skipped / failed",
    )
    git_export_error = Column(Text, nullable=True)
    git_exported_at = Column(DateTime, nullable=True)

    published_from_draft_id = Column(
        Integer,
        ForeignKey("device_protocol_drafts.id", use_alter=True, name="fk_ver_draft_id"),
        nullable=True,
    )

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    spec = relationship(
        "DeviceProtocolSpec",
        back_populates="versions",
        foreign_keys=[spec_id],
    )


class DeviceProtocolDraft(Base):
    """设备协议草稿

    - 克隆场景：base_version_id 不空，spec_id 不空
    - 新建设备场景：spec_id 可空，pending_spec_meta 写入待建 spec 信息；publish 时创建 Spec
    """

    __tablename__ = "device_protocol_drafts"

    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(
        Integer,
        ForeignKey("device_protocol_specs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    base_version_id = Column(
        Integer,
        ForeignKey("device_protocol_versions.id"),
        nullable=True,
    )
    protocol_family = Column(String(50), nullable=False, index=True)
    source_type = Column(
        String(20),
        nullable=False,
        default="clone",
        comment="clone / scratch / import",
    )

    name = Column(String(200), nullable=False)
    # target_version: 早期版本强制填写；现在保留以便迁移/兼容，新建草稿无需填。
    # publish 时若为空，自动按 base_version.version_name 升主版本（V1.0→V2.0）。
    target_version = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)

    spec_json = Column(JSON, nullable=False, default=dict)
    pending_spec_meta = Column(
        JSON,
        nullable=True,
        comment="新建设备时的 spec 元数据（ata_code/device_id/device_name/parent_path）",
    )

    status = Column(
        String(20),
        nullable=False,
        default="draft",
        comment="draft / pending / rejected / approved / published",
    )
    submit_note = Column(Text, nullable=True)

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    published_version_id = Column(
        Integer,
        ForeignKey("device_protocol_versions.id", use_alter=True, name="fk_draft_pub_ver"),
        nullable=True,
    )

    spec = relationship(
        "DeviceProtocolSpec",
        back_populates="drafts",
        foreign_keys=[spec_id],
    )
    change_requests = relationship(
        "ProtocolChangeRequest",
        back_populates="device_draft",
        foreign_keys="ProtocolChangeRequest.device_draft_id",
    )
