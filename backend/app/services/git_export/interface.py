# -*- coding: utf-8 -*-
"""Git 导出层接口"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class ExportResult:
    status: str  # exported / skipped / failed
    commit_hash: Optional[str] = None
    tag: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class GitExporter(Protocol):
    """把设备协议版本写出到 Git 仓库的接口"""

    backend_name: str

    async def export_version(
        self,
        *,
        protocol_family: str,
        ata_code: Optional[str],
        device_id: str,
        device_name: str,
        version_name: str,
        spec_json: Dict[str, Any],
        commit_message: str,
        author: str,
    ) -> ExportResult:
        ...

    async def delete_version(
        self,
        *,
        protocol_family: str,
        ata_code: Optional[str],
        device_id: str,
        version_name: str,
        commit_message: str,
        author: str,
    ) -> ExportResult:
        ...
