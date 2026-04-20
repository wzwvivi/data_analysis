# -*- coding: utf-8 -*-
"""Git 审计导出层（方案 2：DB 主存 + Git 审计副本）

职责：
- 把 ``DeviceProtocolVersion`` 已发布快照落到 ATA 级 Git 仓库；
- 出错不阻塞 publish（publish 走 DB 事务；Git 写入失败记录 ``git_export_status=failed``）。

M1：只提供 ``NoopGitExporter`` 占位，``git_export_status`` 被标为 ``skipped``。
M2：新增 ``LocalSubprocessGitExporter``（复用 ATA 仓库 + 每仓库 asyncio.Lock）。
"""
from .interface import GitExporter, ExportResult
from .noop import NoopGitExporter

__all__ = ["GitExporter", "ExportResult", "NoopGitExporter", "get_git_exporter"]


def get_git_exporter() -> GitExporter:
    """获取当前配置的 Git 导出器实现。

    M1 统一返回 Noop；M2 根据环境变量 ``DEVICE_PROTOCOL_GIT_BACKEND`` 选择。
    """
    return NoopGitExporter()
