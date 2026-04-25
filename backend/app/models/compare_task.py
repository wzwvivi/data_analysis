# -*- coding: utf-8 -*-
"""
双交换机数据比对任务模型

用于保存两个交换机抓包文件的比对任务及结果
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.orm import relationship

from ..database import Base


class CompareTask(Base):
    """双交换机比对任务"""
    __tablename__ = "compare_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    filename_1 = Column(String(255), nullable=False, comment="交换机1文件名")
    filename_2 = Column(String(255), nullable=False, comment="交换机2文件名")
    file_path_1 = Column(String(500), nullable=False, comment="交换机1文件路径")
    file_path_2 = Column(String(500), nullable=False, comment="交换机2文件路径")
    protocol_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=False, comment="TSN 网络协议版本 ID")
    bundle_version_id = Column(
        Integer, ForeignKey("protocol_versions.id"), nullable=True,
        comment="本次比对使用的 Bundle 版本（默认与 protocol_version_id 相同，MR4 版本锁定）",
    )
    status = Column(String(20), default="pending", comment="状态: pending/processing/completed/failed")
    progress = Column(Integer, default=0, comment="进度 0-100")
    error_message = Column(Text, comment="错误信息")
    
    # 检查1: 记录时间同步性
    switch1_first_ts = Column(Float, comment="交换机1首包时间戳")
    switch2_first_ts = Column(Float, comment="交换机2首包时间戳")
    time_diff_ms = Column(Float, comment="首包时间差(毫秒)")
    sync_result = Column(String(20), comment="同步检查结果: pass/warning/fail")
    
    # 检查2: 端口覆盖完整性汇总
    expected_port_count = Column(Integer, default=0, comment="TSN 网络协议中定义的端口总数")
    both_present_count = Column(Integer, default=0, comment="两边都有数据的端口数")
    missing_count = Column(Integer, default=0, comment="至少一边缺失的端口数")
    
    # 检查3: 周期端口数据连续性汇总
    periodic_port_count = Column(Integer, default=0, comment="周期类端口总数")
    ports_with_gaps = Column(Integer, default=0, comment="存在丢包的端口数")
    total_gap_count = Column(Integer, default=0, comment="总丢包段数")
    
    # 检查4: 端口周期正确性与抖动分析汇总
    jitter_threshold_pct = Column(Float, default=10.0, comment="抖动阈值百分比")
    timing_checked_port_count = Column(Integer, default=0, comment="检查的周期端口数")
    timing_pass_count = Column(Integer, default=0, comment="周期正确性通过的端口数")
    timing_warning_count = Column(Integer, default=0, comment="周期正确性警告的端口数")
    timing_fail_count = Column(Integer, default=0, comment="周期正确性失败的端口数")
    
    # 综合结论
    overall_result = Column(String(20), comment="综合结论: pass/warning/fail")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, comment="完成时间")
    
    # 关系
    port_results = relationship("ComparePortResult", back_populates="compare_task", cascade="all, delete-orphan")
    gap_records = relationship("CompareGapRecord", back_populates="compare_task", cascade="all, delete-orphan")
    port_timing_results = relationship("ComparePortTimingResult", back_populates="compare_task", cascade="all, delete-orphan")


class ComparePortResult(Base):
    """端口级比对结果"""
    __tablename__ = "compare_port_results"
    
    id = Column(Integer, primary_key=True, index=True)
    compare_task_id = Column(Integer, ForeignKey("compare_tasks.id"), nullable=False)
    port_number = Column(Integer, nullable=False, comment="端口号")
    source_device = Column(String(100), comment="源设备名称")
    message_name = Column(String(100), comment="消息名称")
    period_ms = Column(Float, comment="周期(毫秒)")
    is_periodic = Column(Boolean, default=False, comment="是否为周期类数据")
    
    # 检查2: 端口覆盖
    in_switch1 = Column(Boolean, default=False, comment="交换机1是否有数据")
    in_switch2 = Column(Boolean, default=False, comment="交换机2是否有数据")
    switch1_count = Column(Integer, default=0, comment="交换机1包数")
    switch2_count = Column(Integer, default=0, comment="交换机2包数")
    switch1_first_ts = Column(Float, comment="交换机1首包时间戳")
    switch1_last_ts = Column(Float, comment="交换机1末包时间戳")
    switch2_first_ts = Column(Float, comment="交换机2首包时间戳")
    switch2_last_ts = Column(Float, comment="交换机2末包时间戳")
    count_diff = Column(Integer, default=0, comment="包数差值(绝对值)")
    
    # 检查3: 数据连续性
    gap_count_switch1 = Column(Integer, default=0, comment="交换机1丢包段数")
    gap_count_switch2 = Column(Integer, default=0, comment="交换机2丢包段数")
    
    # 结论
    result = Column(String(20), comment="结果: pass/warning/fail")
    detail = Column(Text, comment="详细说明")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    compare_task = relationship("CompareTask", back_populates="port_results")


class CompareGapRecord(Base):
    """丢包时间段记录"""
    __tablename__ = "compare_gap_records"
    
    id = Column(Integer, primary_key=True, index=True)
    compare_task_id = Column(Integer, ForeignKey("compare_tasks.id"), nullable=False)
    port_number = Column(Integer, nullable=False, comment="端口号")
    switch_index = Column(Integer, nullable=False, comment="交换机编号: 1或2")
    
    # 丢包区间
    gap_start_ts = Column(Float, nullable=False, comment="丢包起始时间戳")
    gap_end_ts = Column(Float, nullable=False, comment="丢包结束时间戳")
    gap_duration_ms = Column(Float, nullable=False, comment="间隔时长(毫秒)")
    
    # 预期信息
    expected_period_ms = Column(Float, nullable=False, comment="端口预期周期(毫秒)")
    estimated_missing_packets = Column(Integer, comment="预估缺失包数")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    compare_task = relationship("CompareTask", back_populates="gap_records")


class ComparePortTimingResult(Base):
    """端口周期正确性与抖动分析结果"""
    __tablename__ = "compare_port_timing_results"
    
    id = Column(Integer, primary_key=True, index=True)
    compare_task_id = Column(Integer, ForeignKey("compare_tasks.id"), nullable=False)
    port_number = Column(Integer, nullable=False, comment="端口号")
    switch_index = Column(Integer, nullable=False, comment="交换机编号: 1或2")
    source_device = Column(String(100), comment="源设备名称")
    message_name = Column(String(100), comment="消息名称")
    
    # 预期周期
    expected_period_ms = Column(Float, nullable=False, comment="TSN 网络协议预期周期(毫秒)")
    
    # 包数统计
    packet_count = Column(Integer, nullable=False, comment="总包数")
    total_intervals = Column(Integer, nullable=False, comment="总间隔数(包数-1)")
    
    # 实际间隔统计
    actual_mean_interval_ms = Column(Float, comment="实际平均间隔(毫秒)")
    actual_median_interval_ms = Column(Float, comment="实际中位数间隔(毫秒)")
    actual_std_interval_ms = Column(Float, comment="实际标准差(毫秒)")
    actual_min_interval_ms = Column(Float, comment="实际最小间隔(毫秒)")
    actual_max_interval_ms = Column(Float, comment="实际最大间隔(毫秒)")
    
    # 抖动分析
    jitter_pct = Column(Float, comment="抖动百分比 (标准差/预期周期*100)")
    within_threshold_count = Column(Integer, comment="在阈值范围内的间隔数")
    compliance_rate_pct = Column(Float, comment="达标率百分比")
    
    # 结论
    result = Column(String(20), comment="结果: pass/warning/fail")
    detail = Column(Text, comment="详细说明")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    compare_task = relationship("CompareTask", back_populates="port_timing_results")
