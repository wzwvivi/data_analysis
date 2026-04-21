# -*- coding: utf-8 -*-
"""协议库数据模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class ParserProfile(Base):
    """解析版本配置 - 用户选择的解析程序"""
    __tablename__ = "parser_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, comment="解析版本名称，如 JZXPDR113B")
    version = Column(String(50), nullable=False, comment="版本号，如 20260113")
    device_model = Column(String(100), comment="设备型号")
    protocol_family = Column(String(50), comment="协议族标识，如 irs/xpdr，同族不同版本共享")
    parser_key = Column(String(100), nullable=False, unique=True, comment="解析器标识，如 jzxpdr113b_v20260113")
    protocol_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=True, comment="关联的TSN网络配置版本")
    is_active = Column(Boolean, default=True, comment="是否可用")
    description = Column(Text, comment="说明")
    supported_ports = Column(String(500), comment="支持的端口列表，逗号分隔")
    output_fields = Column(Text, comment="输出字段模板JSON")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Protocol(Base):
    """协议定义"""
    __tablename__ = "protocols"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, comment="协议名称")
    description = Column(Text, comment="协议描述")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联版本
    versions = relationship("ProtocolVersion", back_populates="protocol", cascade="all, delete-orphan")


# ── 协议版本可用性状态枚举（字符串值落库，避免 Enum 迁移痛点） ──
AVAILABILITY_AVAILABLE = "Available"
AVAILABILITY_PENDING_CODE = "PendingCode"
AVAILABILITY_DEPRECATED = "Deprecated"
AVAILABILITY_STATUSES = (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_PENDING_CODE,
    AVAILABILITY_DEPRECATED,
)


class ProtocolVersion(Base):
    """协议版本"""
    __tablename__ = "protocol_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(Integer, ForeignKey("protocols.id"), nullable=False)
    version = Column(String(50), nullable=False, comment="版本号")
    source_file = Column(String(255), comment="来源文件名")
    description = Column(Text, comment="版本描述")
    created_at = Column(DateTime, default=datetime.utcnow)

    # 版本生命周期：Available(可选池) / PendingCode(待代码就绪) / Deprecated(弃用)
    availability_status = Column(
        String(20),
        default=AVAILABILITY_AVAILABLE,
        nullable=False,
        comment="可用性状态: Available / PendingCode / Deprecated",
    )
    activated_at = Column(DateTime, nullable=True, comment="进入 Available 的时间")
    activated_by = Column(String(64), nullable=True, comment="执行激活的管理员用户名")
    forced_activation = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否绕过就绪检查强制激活（审计用）",
    )

    # ── MR3 激活闸门 ──
    activation_report_json = Column(
        Text, nullable=True,
        comment="就绪度体检结果（JSON 字符串），由 protocol_activation_service 生成",
    )
    activation_report_generated_at = Column(
        DateTime, nullable=True, comment="体检 JSON 生成时间",
    )
    generated_artifacts_json = Column(
        Text, nullable=True,
        comment="发布时自动生成的代码产物元数据（JSON 列表：path/sha256/generated_at），正文内容在磁盘上",
    )
    activation_force_reason = Column(
        Text, nullable=True,
        comment="强制激活时必填的理由（审计用）",
    )
    # 提交者在发起审批时勾选的"激活后需知会团队"列表，例如 ["fms","fcc"]
    # 由 publish 从对应 CR 拷贝过来；激活时据此给相应角色发站内通知。
    notify_teams = Column(
        JSON, nullable=True, default=list,
        comment="激活后知会团队代码列表（fms/fcc/tsn 等）",
    )

    # 关联
    protocol = relationship("Protocol", back_populates="versions")
    ports = relationship("PortDefinition", back_populates="protocol_version", cascade="all, delete-orphan")


class PortDefinition(Base):
    """端口定义"""
    __tablename__ = "port_definitions"
    
    id = Column(Integer, primary_key=True, index=True)
    protocol_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=False)
    port_number = Column(Integer, nullable=False, comment="UDP端口号")
    message_name = Column(String(100), comment="消息名称")
    source_device = Column(String(100), comment="源设备名称")
    target_device = Column(String(100), comment="目标设备名称")
    multicast_ip = Column(String(50), comment="组播IP")
    data_direction = Column(String(20), comment="数据方向: uplink/downlink/network")
    period_ms = Column(Float, comment="周期(毫秒)")
    description = Column(Text, comment="描述（对应 ICD 的「备注」列）")
    # 协议族（权威），如 irs/xpdr/bms800v/...；为空时由 PORT_FAMILY_MAP 兜底
    protocol_family = Column(String(50), nullable=True, comment="端口所属解析器族")
    # 端口角色（ICD 维度，用于上层模块选择端口），如 tsn_anomaly/fms_event/fcc_event/auto_flight
    port_role = Column(String(50), nullable=True, comment="端口业务角色（tsn_anomaly/fms_event/fcc_event/auto_flight/other）")

    # ── ICD 6.0.x 原表头映射（扩展列，不影响历史解析逻辑） ──
    message_id = Column(String(64), nullable=True, comment="ICD 消息编号")
    source_interface_id = Column(String(64), nullable=True, comment="ICD 消息源端接口编号（上行/网络交互）")
    port_id_label = Column(String(64), nullable=True, comment="ICD PortID（上行/网络交互，字面值）")
    diu_id = Column(String(64), nullable=True, comment="ICD DIU编号")
    diu_id_set = Column(String(200), nullable=True, comment="ICD DIU编号集合（下行）")
    diu_recv_mode = Column(String(100), nullable=True, comment="ICD DIU消息接收形式（下行）")
    tsn_source_ip = Column(String(100), nullable=True, comment="ICD TSN消息源端IP（下行）")
    diu_ip = Column(String(100), nullable=True, comment="ICD 承接转换的DIU IP（下行）")
    dataset_path = Column(String(200), nullable=True, comment="ICD DataSet传递路径（下行）")
    data_real_path = Column(String(200), nullable=True, comment="ICD 数据实际路径（下行）")
    final_recv_device = Column(String(100), nullable=True, comment="ICD 最终接收端设备（下行）")

    # 关联
    protocol_version = relationship("ProtocolVersion", back_populates="ports")
    fields = relationship("FieldDefinition", back_populates="port", cascade="all, delete-orphan")


class FieldDefinition(Base):
    """字段定义"""
    __tablename__ = "field_definitions"
    
    id = Column(Integer, primary_key=True, index=True)
    port_id = Column(Integer, ForeignKey("port_definitions.id"), nullable=False)
    field_name = Column(String(100), nullable=False, comment="字段名称")
    field_offset = Column(Integer, nullable=False, comment="字节偏移")
    field_length = Column(Integer, nullable=False, comment="字节长度")
    data_type = Column(String(50), default="bytes", comment="数据类型: int8/int16/int32/uint8/uint16/uint32/float32/float64/bytes")
    scale_factor = Column(Float, default=1.0, comment="缩放系数")
    unit = Column(String(50), comment="单位")
    description = Column(Text, comment="描述")
    byte_order = Column(String(10), default="big", comment="字节序: big/little")
    
    # 关联
    port = relationship("PortDefinition", back_populates="fields")
