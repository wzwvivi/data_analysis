# -*- coding: utf-8 -*-
"""管理员上传的平台共享 TSN 抓包（保留最近 N 天）"""
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text

from ..database import Base


class SharedTsnFile(Base):
    __tablename__ = "shared_tsn_files"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    experiment_date = Column(Date, nullable=True, comment="实验日期")
    experiment_label = Column(String(500), nullable=True, comment="实验说明/名称")
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
