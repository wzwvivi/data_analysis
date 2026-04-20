# -*- coding: utf-8 -*-
"""解析任务数据模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON

from ..database import Base


class ParseTask(Base):
    """解析任务"""
    __tablename__ = "parse_tasks"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False, comment="上传文件名")
    display_name = Column(String(255), nullable=True, comment="用户自定义任务名（为空则回退到 filename）")
    tags = Column(JSON, comment="用户标签列表")
    file_path = Column(String(500), nullable=False, comment="文件存储路径")
    file_size = Column(Integer, nullable=True, comment="原始文件字节数")
    parser_profile_id = Column(Integer, ForeignKey("parser_profiles.id"), nullable=True, comment="内置协议解析器ID(单解析器兼容)")
    parser_profile_ids = Column(JSON, comment="多解析器ID列表(旧字段，兼容)")
    device_parser_map = Column(JSON, comment="设备到解析器映射: {device_name: parser_profile_id}")
    protocol_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=True, comment="TSN网络配置版本ID")
    status = Column(String(20), default="pending", comment="状态: pending/processing/completed/failed/cancelled")
    stage = Column(String(50), nullable=True, comment="解析细分阶段，如 reading/parsing/saving/finalizing")
    selected_ports = Column(JSON, comment="选择解析的端口列表")
    selected_devices = Column(JSON, comment="选择的设备列表")
    total_packets = Column(Integer, default=0, comment="总包数")
    parsed_packets = Column(Integer, default=0, comment="已解析包数")
    progress = Column(Integer, default=0, comment="解析进度 0-100（按文件读取字节估算）")
    cancel_requested = Column(Integer, default=0, comment="取消请求标志(0/1)，由任务中心写入，子进程协作检查")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True, comment="实际开始解析时间，用于估算剩余时长")
    completed_at = Column(DateTime, comment="完成时间")


class ParseResult(Base):
    """解析结果元数据"""
    __tablename__ = "parse_results"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("parse_tasks.id"), nullable=False)
    port_number = Column(Integer, nullable=False, comment="端口号")
    message_name = Column(String(100), comment="消息名称")
    parser_profile_id = Column(Integer, ForeignKey("parser_profiles.id"), nullable=True, comment="解析器ID")
    parser_profile_name = Column(String(100), comment="解析器名称")
    source_device = Column(String(100), comment="源设备名称")
    record_count = Column(Integer, default=0, comment="记录数")
    result_file = Column(String(500), comment="结果文件路径(parquet)")
    time_start = Column(DateTime, comment="数据起始时间")
    time_end = Column(DateTime, comment="数据结束时间")
    created_at = Column(DateTime, default=datetime.utcnow)
