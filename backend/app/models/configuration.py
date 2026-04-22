# -*- coding: utf-8 -*-
"""构型管理模型

业务定义：
  - 飞机构型（AircraftConfiguration）：相对稳定的基线，绑定 TSN/ICD 协议版本与
    一组设备协议版本；决定了该架次下所有协议层面的内容。
  - 软件构型（SoftwareConfiguration）：对应《软件编号（首飞构型定义A版）.xlsx》
    里的一"列"，即一次试验快照下全机设备的软件版本号组合。
  - 设备库（Device）：Excel 前 13 列的静态元数据（团队/EATA/设备名/DM号/软件名等）。
  - 试验架次（SharedSortie）= 一个飞机构型 × 一个软件构型，两者都是静态绑定。

DM 号（device_dm_number）在 Excel 里会重复（同型号多台），所以 Device 的"业务唯一键"
使用 (team, device_cn_name, software_cn_name)，DM 号仅作为信息列。
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..database import Base


# ── 软件构型来源 ──
SW_CONFIG_SOURCE_EXCEL = "excel"
SW_CONFIG_SOURCE_MANUAL = "manual"
SW_CONFIG_SOURCES = (SW_CONFIG_SOURCE_EXCEL, SW_CONFIG_SOURCE_MANUAL)


class Device(Base):
    """设备主数据（一台物理设备对应一条；例如电驱系统1/2/3... 各一条）"""

    __tablename__ = "configuration_devices"
    __table_args__ = (
        UniqueConstraint(
            "team",
            "device_cn_name",
            "software_cn_name",
            name="uq_configuration_device_identity",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String(100), nullable=False, index=True, comment="软件归属团队（如 电推进团队）")
    eata_chapter = Column(String(200), nullable=True, comment="EATA 章节号-系统名称")
    device_cn_name = Column(String(200), nullable=False, comment="设备中文名称")
    device_dm_number = Column(String(100), nullable=True, index=True, comment="设备 DM 号")
    software_cn_name = Column(String(200), nullable=False, comment="软件中文名称")
    software_level = Column(String(20), nullable=True, comment="软件等级 A/B/C/NA")
    is_cds_resident = Column(Boolean, nullable=True, comment="是否显控驻留软件")
    is_field_loadable = Column(Boolean, nullable=True, comment="是否外场可加载")
    is_proprietary = Column(Boolean, nullable=True, comment="是否为自研软件")
    supplier = Column(String(200), nullable=True, comment="软件供应商")
    is_new_dev = Column(Boolean, nullable=True, comment="是否新研软件")
    has_software = Column(Boolean, nullable=True, comment="是否有软件")
    remarks = Column(Text, nullable=True, comment="备注（用户自填）")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AircraftConfiguration(Base):
    """飞机构型：命名基线，绑定一个 TSN 协议版本与一组设备协议版本"""

    __tablename__ = "aircraft_configurations"
    __table_args__ = (
        UniqueConstraint("name", name="uq_aircraft_configuration_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, comment="名称，如 'CE-25A 0号机 VA'")
    version = Column(String(50), nullable=True, comment="版本号，如 'VA'")
    description = Column(Text, nullable=True)

    tsn_protocol_version_id = Column(
        Integer,
        ForeignKey("protocol_versions.id", ondelete="SET NULL"),
        nullable=True,
        comment="绑定的 TSN 网络/ICD 协议版本",
    )

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    device_protocol_links = relationship(
        "AircraftConfigDeviceProtocolLink",
        back_populates="aircraft_config",
        cascade="all, delete-orphan",
    )


class AircraftConfigDeviceProtocolLink(Base):
    """飞机构型 × 设备协议版本 多对多关联"""

    __tablename__ = "aircraft_config_device_protocol_links"
    __table_args__ = (
        UniqueConstraint(
            "aircraft_config_id",
            "device_protocol_version_id",
            name="uq_aircraft_config_device_protocol",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    aircraft_config_id = Column(
        Integer,
        ForeignKey("aircraft_configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_protocol_version_id = Column(
        Integer,
        ForeignKey("device_protocol_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    aircraft_config = relationship(
        "AircraftConfiguration", back_populates="device_protocol_links"
    )


class SoftwareConfiguration(Base):
    """软件构型：命名的软件版本快照（Excel 中的一列）"""

    __tablename__ = "software_configurations"
    __table_args__ = (
        UniqueConstraint("name", name="uq_software_configuration_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False, comment="构型名称，如 '首飞构型定义A版' 或 '机上试验2026.04.09'")
    snapshot_date = Column(Date, nullable=True, comment="构型对应的试验日期（可从名称识别）")
    source = Column(
        String(16),
        nullable=False,
        default=SW_CONFIG_SOURCE_MANUAL,
        comment="来源：excel / manual",
    )
    source_file = Column(String(500), nullable=True, comment="导入源文件名（excel 来源时填写）")
    description = Column(Text, nullable=True)

    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entries = relationship(
        "SoftwareConfigurationEntry",
        back_populates="software_config",
        cascade="all, delete-orphan",
    )


class SoftwareConfigurationEntry(Base):
    """软件构型条目：一个设备在一个构型下的软件版本号"""

    __tablename__ = "software_configuration_entries"
    __table_args__ = (
        UniqueConstraint(
            "software_config_id",
            "device_id",
            name="uq_software_configuration_entry_device",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    software_config_id = Column(
        Integer,
        ForeignKey("software_configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id = Column(
        Integer,
        ForeignKey("configuration_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    software_version_code = Column(
        String(300),
        nullable=True,
        comment="软件版本号原始文本，如 'IEE26-EPS2-A001(VA.6.4.13)'",
    )
    change_note = Column(Text, nullable=True, comment="较上次/较基线的更改说明")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    software_config = relationship("SoftwareConfiguration", back_populates="entries")
    device = relationship("Device")
