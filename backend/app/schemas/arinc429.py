# -*- coding: utf-8 -*-
"""ARINC429 协议管理 API 模型"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ----- 设备树 -----


class Arinc429DeviceNode(BaseModel):
    """设备树节点（递归 children）"""

    id: int
    device_id: str
    name: str
    parent_id: Optional[int] = None
    is_device: bool = False
    device_version: Optional[str] = "V1.0"
    current_version_name: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    children: List["Arinc429DeviceNode"] = Field(default_factory=list)
    versions: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        from_attributes = True


Arinc429DeviceNode.model_rebuild()


class Arinc429SystemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    parent_id: Optional[int] = None
    description: Optional[str] = None


class Arinc429DeviceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    parent_id: int = Field(..., description="父节点数据库 id")
    device_id: Optional[str] = Field(
        None,
        max_length=200,
        description="可选稳定 ID；不传则根据名称自动生成",
    )
    description: Optional[str] = Field(None, max_length=2000)


# ----- Label -----


class Arinc429LabelPayload(BaseModel):
    """与协议平台 JSON 对齐的 Label 结构"""

    label_oct: str = ""
    name: str = ""
    direction: Optional[str] = ""
    sources: Optional[List[str]] = None
    data_type: Optional[str] = ""
    unit: Optional[str] = ""
    range_value: Optional[str] = Field(None, alias="range", description="量程/范围描述")
    resolution: Optional[float] = None
    reserved_bits: Optional[str] = ""
    notes: Optional[str] = ""
    discrete_bits: Optional[Dict[str, str]] = None
    special_fields: Optional[List[Dict[str, Any]]] = None
    bnr_fields: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


class Arinc429LabelResponse(BaseModel):
    id: int
    label_oct: str
    name: str
    direction: Optional[str] = None
    sources: Optional[List[str]] = None
    data_type: Optional[str] = None
    unit: Optional[str] = None
    range: Optional[str] = None
    resolution: Optional[float] = None
    reserved_bits: Optional[str] = None
    notes: Optional[str] = None
    discrete_bits: Optional[Dict[str, Any]] = None
    special_fields: Optional[List[Any]] = None
    bnr_fields: Optional[List[Any]] = None
    protocol_version_id: Optional[int] = None


class Arinc429LabelsSaveRequest(BaseModel):
    labels: List[Arinc429LabelPayload]
    protocol_version_id: Optional[int] = None
    change_summary: Optional[str] = None
    bump_version: bool = Field(
        False,
        description="是否在保存前将设备 device_version 递增并写入历史",
    )


# ----- 协议版本 -----


class Arinc429ProtocolVersionResponse(BaseModel):
    id: int
    version_name: str
    version: str


class Arinc429VersionHistoryItem(BaseModel):
    version: str
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None
    change_summary: Optional[str] = None
    diff_summary: Optional[Dict[str, Any]] = None
    label_count: int = 0


class Arinc429DeviceTreeResponse(BaseModel):
    items: List[Arinc429DeviceNode]
