# -*- coding: utf-8 -*-
"""用户与角色"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin | user
    created_at = Column(DateTime, default=datetime.utcnow)
