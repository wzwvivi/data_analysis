# -*- coding: utf-8 -*-
"""协议相关的Pydantic模型"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class FieldDefinitionResponse(BaseModel):
    """字段定义响应"""
    id: int
    field_name: str
    field_offset: int
    field_length: int
    data_type: str
    scale_factor: float
    unit: Optional[str] = None
    description: Optional[str] = None
    byte_order: str = "big"
    
    class Config:
        from_attributes = True


class PortDefinitionResponse(BaseModel):
    """端口定义响应"""
    id: int
    port_number: int
    message_name: Optional[str] = None
    source_device: Optional[str] = None
    target_device: Optional[str] = None
    multicast_ip: Optional[str] = None
    data_direction: Optional[str] = None
    period_ms: Optional[float] = None
    description: Optional[str] = None
    fields: List[FieldDefinitionResponse] = []
    
    class Config:
        from_attributes = True


class ProtocolVersionResponse(BaseModel):
    """协议版本响应"""
    id: int
    version: str
    source_file: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    port_count: int = 0
    
    class Config:
        from_attributes = True


class ProtocolVersionCreate(BaseModel):
    """创建协议版本"""
    version: str
    description: Optional[str] = None


class ProtocolResponse(BaseModel):
    """协议响应"""
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    versions: List[ProtocolVersionResponse] = []
    
    class Config:
        from_attributes = True


class ProtocolCreate(BaseModel):
    """创建协议"""
    name: str
    description: Optional[str] = None


class ProtocolListResponse(BaseModel):
    """协议列表响应"""
    total: int
    items: List[ProtocolResponse]


# ========== 解析版本相关 Schema ==========

class ParserProfileResponse(BaseModel):
    """解析版本响应"""
    id: int
    name: str
    version: str
    device_model: Optional[str] = None
    protocol_family: Optional[str] = None
    parser_key: str
    is_active: bool = True
    description: Optional[str] = None
    supported_ports: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ParserProfileListResponse(BaseModel):
    """解析版本列表响应"""
    total: int
    items: List[ParserProfileResponse]
