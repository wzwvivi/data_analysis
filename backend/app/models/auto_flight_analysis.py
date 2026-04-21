# -*- coding: utf-8 -*-
"""
自动飞行性能分析模型
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, JSON
from sqlalchemy.orm import relationship

from ..database import Base


class AutoFlightAnalysisTask(Base):
    __tablename__ = "auto_flight_analysis_tasks"

    id = Column(Integer, primary_key=True, index=True)
    parse_task_id = Column(Integer, ForeignKey("parse_tasks.id"), nullable=True)
    pcap_filename = Column(String(200), nullable=True)
    pcap_file_path = Column(String(500), nullable=True)
    name = Column(String(200), nullable=True)
    source_type = Column(String(30), default="standalone", comment="standalone/parse_task/shared")
    status = Column(String(20), default="pending", comment="pending/processing/completed/failed")
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    touchdown_count = Column(Integer, default=0)
    steady_count = Column(Integer, default=0)
    # MR4：本次分析锁定的 TSN 协议版本（bundle）。目前仅做审计/展示用途，
    # 未来若 AutoFlight 规则开始从 bundle 读取端口/字段可直接复用此列。
    bundle_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    parse_task = relationship("ParseTask", backref="auto_flight_analysis_tasks")
    touchdowns = relationship("TouchdownAnalysisResult", back_populates="analysis_task", cascade="all, delete-orphan")
    steady_states = relationship("SteadyStateAnalysisResult", back_populates="analysis_task", cascade="all, delete-orphan")


class TouchdownAnalysisResult(Base):
    __tablename__ = "touchdown_analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("auto_flight_analysis_tasks.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    touchdown_ts = Column(Float, nullable=False)
    touchdown_time = Column(String(64), nullable=True)

    irs1_vz = Column(Float, nullable=True)
    irs2_vz = Column(Float, nullable=True)
    irs3_vz = Column(Float, nullable=True)
    vz_spread = Column(Float, nullable=True)
    irs1_az_peak = Column(Float, nullable=True)
    irs2_az_peak = Column(Float, nullable=True)
    irs3_az_peak = Column(Float, nullable=True)
    az_peak_spread = Column(Float, nullable=True)

    rating = Column(String(20), default="normal")
    summary = Column(Text, nullable=True)
    chart_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_task = relationship("AutoFlightAnalysisTask", back_populates="touchdowns")


class SteadyStateAnalysisResult(Base):
    __tablename__ = "steady_state_analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    analysis_task_id = Column(Integer, ForeignKey("auto_flight_analysis_tasks.id"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    start_ts = Column(Float, nullable=False)
    end_ts = Column(Float, nullable=False)
    start_time = Column(String(64), nullable=True)
    end_time = Column(String(64), nullable=True)
    duration_s = Column(Float, nullable=False)
    mode_label = Column(String(120), nullable=True)

    alt_bias = Column(Float, nullable=True)
    alt_rms = Column(Float, nullable=True)
    alt_max_abs = Column(Float, nullable=True)
    lat_bias = Column(Float, nullable=True)
    lat_rms = Column(Float, nullable=True)
    lat_max_abs = Column(Float, nullable=True)
    spd_bias = Column(Float, nullable=True)
    spd_rms = Column(Float, nullable=True)
    spd_max_abs = Column(Float, nullable=True)

    rating = Column(String(20), default="normal")
    summary = Column(Text, nullable=True)
    chart_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_task = relationship("AutoFlightAnalysisTask", back_populates="steady_states")
