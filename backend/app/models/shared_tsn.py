# -*- coding: utf-8 -*-
"""管理员上传的平台共享 TSN 抓包（保留最近 N 天）"""
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import relationship

from ..database import Base


class SharedSortie(Base):
    """试验架次：一次完整试验下挂载多路数据文件。"""

    __tablename__ = "shared_sorties"

    id = Column(Integer, primary_key=True, index=True)
    sortie_label = Column(String(300), nullable=False, comment="架次名称或编号")
    experiment_date = Column(Date, nullable=True, comment="试验日期")
    remarks = Column(Text, nullable=True, comment="备注")
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    files = relationship(
        "SharedTsnFile",
        back_populates="sortie",
        foreign_keys="SharedTsnFile.sortie_id",
    )


class SharedTsnFile(Base):
    __tablename__ = "shared_tsn_files"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True, comment="文件字节数")
    experiment_date = Column(Date, nullable=True, comment="实验日期（兼容旧字段）")
    experiment_label = Column(String(500), nullable=True, comment="实验说明/名称（兼容旧字段）")
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sortie_id = Column(Integer, ForeignKey("shared_sorties.id"), nullable=True, index=True)
    asset_type = Column(String(64), nullable=True, comment="数据种类 key，见 shared_platform_assets")

    video_processing_status = Column(String(32), nullable=True, comment="视频：transcoding|ready|failed|null")
    video_processing_progress = Column(Integer, nullable=True, comment="0–100，仅视频处理")
    video_processing_error = Column(Text, nullable=True)

    sortie = relationship(
        "SharedSortie",
        back_populates="files",
        foreign_keys=[sortie_id],
    )
