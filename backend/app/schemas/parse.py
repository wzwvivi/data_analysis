# -*- coding: utf-8 -*-
"""解析相关的Pydantic模型"""
from datetime import datetime
from typing import Optional, List, Any, Dict
from pydantic import BaseModel


class ParseTaskCreate(BaseModel):
    """创建解析任务"""
    parser_profile_id: Optional[int] = None  # 单解析器(兼容旧接口)
    parser_profile_ids: Optional[List[int]] = None  # 多解析器ID列表(兼容旧接口)
    device_parser_map: Optional[Dict[str, int]] = None  # 设备到解析器映射: {device_name: parser_profile_id}
    protocol_version_id: Optional[int] = None  # TSN网络配置版本ID
    selected_ports: Optional[List[int]] = None  # None表示解析所有端口
    selected_devices: Optional[List[str]] = None  # 选择的设备列表


class ParserProfileSummary(BaseModel):
    """解析器摘要"""
    id: int
    name: str
    version: Optional[str] = None


class DeviceParserInfo(BaseModel):
    """设备-解析器绑定信息"""
    device_name: str
    parser_profile_id: int
    parser_profile_name: Optional[str] = None
    parser_profile_version: Optional[str] = None
    protocol_family: Optional[str] = None


class ParseTaskResponse(BaseModel):
    """解析任务响应"""
    id: int
    filename: str
    display_name: Optional[str] = None
    tags: Optional[List[str]] = None
    file_size: Optional[int] = None
    is_shared_source: bool = False
    parser_profile_id: Optional[int] = None
    parser_profile_ids: Optional[List[int]] = None
    device_parser_map: Optional[Dict[str, int]] = None
    device_parsers: Optional[List[DeviceParserInfo]] = None
    parser_profile_name: Optional[str] = None
    parser_profile_version: Optional[str] = None
    parser_profiles: Optional[List[ParserProfileSummary]] = None
    protocol_version_id: Optional[int] = None
    network_config_name: Optional[str] = None
    network_config_version: Optional[str] = None
    status: str
    stage: Optional[str] = None
    selected_ports: Optional[List[int]] = None
    selected_devices: Optional[List[str]] = None
    total_packets: int
    parsed_packets: int
    progress: int = 0
    cancel_requested: bool = False
    can_rerun: bool = False
    estimated_remaining_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ParseTaskListResponse(BaseModel):
    """解析任务列表响应"""
    total: int
    items: List[ParseTaskResponse]


class ParseResultResponse(BaseModel):
    """解析结果响应"""
    id: int
    task_id: int
    port_number: int
    message_name: Optional[str] = None
    parser_profile_id: Optional[int] = None
    parser_profile_name: Optional[str] = None
    source_device: Optional[str] = None
    record_count: int
    time_start: Optional[datetime] = None
    time_end: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ParsedDataResponse(BaseModel):
    """解析数据响应"""
    port_number: int
    message_name: Optional[str] = None
    total_records: int
    page: int
    page_size: int
    columns: List[str]
    data: List[Dict[str, Any]]


class TimeSeriesDataResponse(BaseModel):
    """时序数据响应"""
    port_number: int
    field_name: str
    timestamps: List[float]
    values: List[Any]
    unit: Optional[str] = None


class PortAnomalyDefaultsResponse(BaseModel):
    """端口异常分析：数值字段与默认跳变阈值"""
    port_number: int
    parser_id: Optional[int] = None
    numeric_fields: List[str]
    default_jump_threshold_pct: Dict[str, float]
    stuck_consecutive_frames: int


class PortAnomalyAnalyzeRequest(BaseModel):
    """端口异常分析请求"""
    fields: List[str]
    parser_id: Optional[int] = None
    jump_threshold_pct_overrides: Optional[Dict[str, float]] = None


class PortAnomalyAnalyzeResponse(BaseModel):
    """端口异常分析结果"""
    port_number: int
    parser_id: Optional[int] = None
    summary: Dict[str, Any]
    jump_events: List[Dict[str, Any]]
    stuck_events: List[Dict[str, Any]]
    stuck_consecutive_frames: int
    message: Optional[str] = None
