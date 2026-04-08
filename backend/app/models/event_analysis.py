# -*- coding: utf-8 -*-
"""
事件分析相关数据模型

用于保存事件分析任务、检查单结果、事件时间线
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class EventAnalysisTask(Base):
    """事件分析任务"""
    __tablename__ = "event_analysis_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    parse_task_id = Column(Integer, ForeignKey("parse_tasks.id"), nullable=True, comment="关联的解析任务ID（独立分析时为 NULL）")
    pcap_filename = Column(String(200), nullable=True, comment="独立分析时的原始 pcap 文件名")
    pcap_file_path = Column(String(500), nullable=True, comment="独立分析时 pcap 文件路径")
    name = Column(String(200), comment="分析任务名称")
    rule_template = Column(String(100), default="default_v1", comment="使用的规则模板标识")
    status = Column(String(20), default="pending", comment="状态: pending/processing/completed/failed")
    progress = Column(Integer, default=0, comment="进度 0-100")
    error_message = Column(Text, comment="错误信息")
    total_checks = Column(Integer, default=0, comment="检查项总数")
    passed_checks = Column(Integer, default=0, comment="通过的检查项数")
    failed_checks = Column(Integer, default=0, comment="失败的检查项数")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, comment="完成时间")
    
    # 关系
    parse_task = relationship("ParseTask", backref="event_analysis_tasks")
    check_results = relationship("EventCheckResult", back_populates="analysis_task", cascade="all, delete-orphan")
    timeline_events = relationship("EventTimelineEvent", back_populates="analysis_task", cascade="all, delete-orphan")


class EventCheckResult(Base):
    """检查单结果 - 每个检查项的结论"""
    __tablename__ = "event_check_results"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("event_analysis_tasks.id"), nullable=False)
    
    # 检查项基本信息
    sequence = Column(Integer, comment="序号")
    check_name = Column(String(200), nullable=False, comment="检查项名称")
    category = Column(String(100), comment="检查分类，如：启动检查、周期检查、响应检查")
    description = Column(Text, comment="检查项描述")
    
    # Wireshark 过滤器（可选，用于追溯）
    wireshark_filter = Column(String(500), comment="Wireshark过滤器表达式")
    
    # 事件描述
    event_time = Column(String(50), comment="事件发生时间，如 13:43:15")
    event_description = Column(Text, comment="事件描述")
    
    # 周期检查
    period_expected = Column(Text, comment="周期性预期结果")
    period_actual = Column(Text, comment="周期性实际结果")
    period_analysis = Column(Text, comment="周期性检查分析")
    period_result = Column(String(20), comment="周期检查结果: pass/fail/na")
    
    # 内容检查
    content_expected = Column(Text, comment="数据预期结果")
    content_actual = Column(Text, comment="数据实际结果")
    content_analysis = Column(Text, comment="数据内容检查分析")
    content_result = Column(String(20), comment="内容检查结果: pass/fail/na")
    
    # 响应检查
    response_expected = Column(Text, comment="响应预期")
    response_actual = Column(Text, comment="实际响应")
    response_analysis = Column(Text, comment="响应分析")
    response_result = Column(String(20), comment="响应检查结果: pass/fail/na")
    
    # 综合结论
    overall_result = Column(String(20), default="pending", comment="综合结论: pass/fail/warning/na")
    
    # 证据和附加数据
    evidence_data = Column(JSON, comment="证据数据，包含原始报文、截图引用等")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    analysis_task = relationship("EventAnalysisTask", back_populates="check_results")


class EventTimelineEvent(Base):
    """事件时间线 - 识别出的关键事件"""
    __tablename__ = "event_timeline_events"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("event_analysis_tasks.id"), nullable=False)
    
    # 时间信息
    timestamp = Column(Float, comment="Unix时间戳")
    time_str = Column(String(50), comment="可读时间字符串，如 13:43:12")
    
    # 设备/来源
    device = Column(String(100), comment="设备名称，如 飞管1、飞管2")
    port = Column(Integer, comment="关联的端口号")
    
    # 事件信息
    event_type = Column(String(50), comment="事件类型: first_send/periodic/state_change/command/response")
    event_name = Column(String(200), comment="事件名称")
    event_description = Column(Text, comment="事件详细描述")
    
    # 关联检查项（可选）
    related_check_id = Column(Integer, ForeignKey("event_check_results.id"), nullable=True)
    
    # 原始数据引用
    raw_data_hex = Column(Text, comment="原始报文十六进制")
    field_values = Column(JSON, comment="解析后的字段值")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    analysis_task = relationship("EventAnalysisTask", back_populates="timeline_events")
    related_check = relationship("EventCheckResult", backref="related_events")
