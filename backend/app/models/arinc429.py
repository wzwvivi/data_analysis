# -*- coding: utf-8 -*-
"""ARINC429 协议管理（设备树、Label、版本历史）— 与 TSN ICD 表分离"""
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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..database import Base


class Arinc429Device(Base):
    """设备树节点：系统文件夹或叶子设备"""

    __tablename__ = "arinc429_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(200), unique=True, nullable=False, index=True, comment="稳定字符串ID，如 ata32_32_3")
    name = Column(String(500), nullable=False)
    parent_id = Column(
        Integer,
        ForeignKey("arinc429_devices.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_device = Column(Boolean, default=False, nullable=False)
    device_version = Column(String(50), default="V1.0")
    current_version_name = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship(
        "Arinc429Device",
        remote_side=[id],
        back_populates="children",
    )
    children = relationship(
        "Arinc429Device",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    protocol_versions = relationship(
        "Arinc429DeviceProtocolVersion",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    labels = relationship(
        "Arinc429Label",
        back_populates="device",
        cascade="all, delete-orphan",
    )
    version_history = relationship(
        "Arinc429VersionHistory",
        back_populates="device",
        cascade="all, delete-orphan",
    )


class Arinc429DeviceProtocolVersion(Base):
    """设备下的协议版本（如 V5.0）"""

    __tablename__ = "arinc429_device_protocol_versions"
    __table_args__ = (
        UniqueConstraint("device_id", "version_name", name="uq_arinc429_dev_ver_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(
        Integer,
        ForeignKey("arinc429_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_name = Column(String(200), nullable=False)
    version = Column(String(50), nullable=False)

    device = relationship("Arinc429Device", back_populates="protocol_versions")
    labels = relationship(
        "Arinc429Label",
        back_populates="protocol_version",
        cascade="all, delete-orphan",
    )


class Arinc429Label(Base):
    """ARINC429 Label 定义"""

    __tablename__ = "arinc429_labels"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "protocol_version_id",
            "label_oct",
            name="uq_arinc429_label_oct_per_dev_ver",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(
        Integer,
        ForeignKey("arinc429_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    protocol_version_id = Column(
        Integer,
        ForeignKey("arinc429_device_protocol_versions.id", ondelete="CASCADE"),
        nullable=True,
    )
    label_oct = Column(String(20), nullable=False)
    name = Column(String(500), nullable=False)
    direction = Column(String(100), nullable=True)
    sources = Column(JSON, nullable=True)  # list[str]
    data_type = Column(String(100), nullable=True)
    unit = Column(String(100), nullable=True)
    range_desc = Column(String(500), nullable=True)
    resolution = Column(Float, nullable=True)
    reserved_bits = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    discrete_bits = Column(JSON, nullable=True)  # dict
    special_fields = Column(JSON, nullable=True)  # list
    bnr_fields = Column(JSON, nullable=True)  # list
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device = relationship("Arinc429Device", back_populates="labels")
    protocol_version = relationship(
        "Arinc429DeviceProtocolVersion",
        back_populates="labels",
    )


class Arinc429VersionHistory(Base):
    """保存 Label 快照，用于历史查看与回滚"""

    __tablename__ = "arinc429_version_history"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(
        Integer,
        ForeignKey("arinc429_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(String(50), nullable=False, comment="历史记录版本号，如 V1.0_snapshot")
    updated_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(100), nullable=True)
    change_summary = Column(String(500), nullable=True)
    diff_summary = Column(JSON, nullable=True)
    label_snapshot = Column(JSON, nullable=True)
    label_count = Column(Integer, default=0)

    device = relationship("Arinc429Device", back_populates="version_history")
