# -*- coding: utf-8 -*-
"""占位 Git 导出器：M1 不真正写 Git，仅把状态标为 skipped"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .interface import ExportResult


class NoopGitExporter:
    backend_name = "noop"

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
        return ExportResult(status="skipped")

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
        return ExportResult(status="skipped")
