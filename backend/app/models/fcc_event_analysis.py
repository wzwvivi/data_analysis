# -*- coding: utf-8 -*-
"""
飞控事件分析相关数据模型（Phase 1b 从原 EventAnalysis 表拆出，独立落表）。

与 :mod:`.fms_event_analysis` 保持完全对称的列结构，只是 `rule_template`
字段被去掉（原先用它区分飞管 / 飞控，新表结构下已无歧义，默认值固定为
``"fcc_v1"``，只作为审计字符串保留）。
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class FccEventAnalysisTask(Base):
    """飞控事件分析任务。"""
    __tablename__ = "fcc_event_analysis_tasks"

    id = Column(Integer, primary_key=True, index=True)
    parse_task_id = Column(Integer, ForeignKey("parse_tasks.id"), nullable=True, comment="关联的解析任务ID（独立分析时为 NULL）")
    bundle_version_id = Column(
        Integer, ForeignKey("protocol_versions.id"), nullable=True,
        comment="本次分析使用的 Bundle 版本（MR4 版本锁定，FCC 走 role 查询）",
    )
    pcap_filename = Column(String(200), nullable=True, comment="独立分析时的原始 pcap 文件名")
    pcap_file_path = Column(String(500), nullable=True, comment="独立分析时 pcap 文件路径")
    name = Column(String(200), comment="分析任务名称")
    rule_template = Column(String(100), default="fcc_v1", comment="规则模板，目前固定 fcc_v1")
    status = Column(String(20), default="pending", comment="状态: pending/processing/completed/failed")
    progress = Column(Integer, default=0, comment="进度 0-100")
    error_message = Column(Text, comment="错误信息")
    total_checks = Column(Integer, default=0, comment="检查项总数")
    passed_checks = Column(Integer, default=0, comment="通过的检查项数")
    failed_checks = Column(Integer, default=0, comment="失败的检查项数")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, comment="完成时间")

    parse_task = relationship("ParseTask", backref="fcc_event_analysis_tasks")
    check_results = relationship("FccEventCheckResult", back_populates="analysis_task", cascade="all, delete-orphan")
    timeline_events = relationship("FccEventTimelineEvent", back_populates="analysis_task", cascade="all, delete-orphan")


class FccEventCheckResult(Base):
    """飞控事件分析检查单结果。"""
    __tablename__ = "fcc_event_check_results"

    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("fcc_event_analysis_tasks.id"), nullable=False)

    sequence = Column(Integer, comment="序号")
    check_name = Column(String(200), nullable=False, comment="检查项名称")
    category = Column(String(100), comment="检查分类")
    description = Column(Text, comment="检查项描述")

    wireshark_filter = Column(String(500), comment="Wireshark过滤器表达式")

    event_time = Column(String(50), comment="事件发生时间")
    event_description = Column(Text, comment="事件描述")

    period_expected = Column(Text, comment="周期性预期结果")
    period_actual = Column(Text, comment="周期性实际结果")
    period_analysis = Column(Text, comment="周期性检查分析")
    period_result = Column(String(20), comment="周期检查结果: pass/fail/na")

    content_expected = Column(Text, comment="数据预期结果")
    content_actual = Column(Text, comment="数据实际结果")
    content_analysis = Column(Text, comment="数据内容检查分析")
    content_result = Column(String(20), comment="内容检查结果: pass/fail/na")

    response_expected = Column(Text, comment="响应预期")
    response_actual = Column(Text, comment="实际响应")
    response_analysis = Column(Text, comment="响应分析")
    response_result = Column(String(20), comment="响应检查结果: pass/fail/na")

    overall_result = Column(String(20), default="pending", comment="综合结论")

    evidence_data = Column(JSON, comment="证据数据")

    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_task = relationship("FccEventAnalysisTask", back_populates="check_results")


class FccEventTimelineEvent(Base):
    """飞控事件分析时间线事件。"""
    __tablename__ = "fcc_event_timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("fcc_event_analysis_tasks.id"), nullable=False)

    timestamp = Column(Float, comment="Unix时间戳")
    time_str = Column(String(50), comment="可读时间字符串")

    device = Column(String(100), comment="设备名称")
    port = Column(Integer, comment="关联的端口号")

    event_type = Column(String(50), comment="事件类型")
    event_name = Column(String(200), comment="事件名称")
    event_description = Column(Text, comment="事件详细描述")

    related_check_id = Column(Integer, ForeignKey("fcc_event_check_results.id"), nullable=True)

    raw_data_hex = Column(Text, comment="原始报文十六进制")
    field_values = Column(JSON, comment="解析后的字段值")

    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_task = relationship("FccEventAnalysisTask", back_populates="timeline_events")
    related_check = relationship("FccEventCheckResult", backref="related_events")
