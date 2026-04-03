# -*- coding: utf-8 -*-
"""协议库数据模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean
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


class ProtocolVersion(Base):
    """协议版本"""
    __tablename__ = "protocol_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    protocol_id = Column(Integer, ForeignKey("protocols.id"), nullable=False)
    version = Column(String(50), nullable=False, comment="版本号")
    source_file = Column(String(255), comment="来源文件名")
    description = Column(Text, comment="版本描述")
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
    description = Column(Text, comment="描述")
    
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
