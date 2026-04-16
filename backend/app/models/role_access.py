# -*- coding: utf-8 -*-
"""角色权限数据模型"""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint

from ..database import Base


class RolePortAccess(Base):
    __tablename__ = "role_port_access"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20), nullable=False, index=True)
    protocol_version_id = Column(Integer, ForeignKey("protocol_versions.id"), nullable=False)
    port_number = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("role", "protocol_version_id", "port_number", name="uq_role_proto_port"),
    )
