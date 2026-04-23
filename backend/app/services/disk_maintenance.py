# -*- coding: utf-8 -*-
"""磁盘维护：结果保留期回收 + 剩余空间守卫。

本模块面向目标部署机（40 GB 磁盘，无 Swap）的磁盘健康做两件事：

1. ``purge_expired_results``：扫描 ``data/results/<task_id>/`` 与
   ``data/exports/<task_id>/``，把对应 ``ParseTask.completed_at`` 早于
   ``RESULT_RETENTION_DAYS`` 天的任务结果整目录删除。**只删磁盘文件，不
   删数据库记录**，保留任务元数据（状态/时间/错误信息）用于审计，只是
   用户再打开时读不到具体解析数据。
2. ``ensure_free_disk``：上传入口调用；当 UPLOAD_DIR 所在文件系统剩余空间
   低于 ``MIN_FREE_DISK_MB`` 时抛 ``InsufficientDiskSpace``，由 API 层转成
   友好报错，避免写满磁盘导致 SQLite WAL 损坏。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import (
    DATA_DIR,
    MIN_FREE_DISK_MB,
    RESULT_RETENTION_DAYS,
    UPLOAD_DIR,
)
from ..models import ParseTask

logger = logging.getLogger(__name__)


class InsufficientDiskSpace(RuntimeError):
    """剩余磁盘空间不足以继续写入。"""


def _free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return -1


def free_disk_mb(path: Optional[Path] = None) -> int:
    """返回指定路径所在分区的剩余空间（MB，取整）。失败时返回 -1。"""
    target = path or UPLOAD_DIR
    free = _free_bytes(target)
    return free // (1024 * 1024) if free >= 0 else -1


def ensure_free_disk(path: Optional[Path] = None) -> None:
    """在接收上传前调用；空间不足抛 ``InsufficientDiskSpace``。

    若 ``MIN_FREE_DISK_MB`` 为 0 则跳过检查（便于本地开发 / 小磁盘环境禁用）。
    """
    if MIN_FREE_DISK_MB <= 0:
        return
    mb = free_disk_mb(path)
    if mb < 0:
        # 读不到分区信息时不阻塞（避免误伤容器内特殊文件系统）
        return
    if mb < MIN_FREE_DISK_MB:
        raise InsufficientDiskSpace(
            f"磁盘剩余 {mb} MB，低于阈值 {MIN_FREE_DISK_MB} MB；请清理历史任务或扩容后重试"
        )


async def purge_expired_results(
    db: AsyncSession,
    retention_days: Optional[int] = None,
) -> int:
    """删除完成时间早于保留期的任务结果目录。

    Returns:
        被删除的任务数量（磁盘上存在且被回收的才计数）。
    """
    days = retention_days if retention_days is not None else RESULT_RETENTION_DAYS
    if days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=days)
    r = await db.execute(
        select(ParseTask.id, ParseTask.completed_at)
        .where(ParseTask.completed_at.is_not(None))
        .where(ParseTask.completed_at < cutoff)
    )
    expired_rows = list(r.all())
    if not expired_rows:
        return 0

    purged = 0
    results_root = DATA_DIR / "results"
    exports_root = DATA_DIR / "exports"
    for task_id, _ in expired_rows:
        for root in (results_root, exports_root):
            p = root / str(task_id)
            if p.is_dir():
                try:
                    shutil.rmtree(p, ignore_errors=True)
                    purged += 1
                except OSError as exc:
                    logger.warning("[DiskMaint] 删除 %s 失败: %s", p, exc)
    if purged:
        logger.info(
            "[DiskMaint] 已回收过期任务结果目录 %d 个（保留 %d 天内）",
            purged,
            days,
        )
    return purged


async def purge_orphan_result_dirs(known_task_ids: Iterable[int]) -> int:
    """扫描 ``data/results`` 下所有 ``<task_id>`` 目录，删除 DB 里已不存在的。

    用于库被手动清理后回收孤立的 parquet 目录。
    """
    results_root = DATA_DIR / "results"
    if not results_root.is_dir():
        return 0
    known = {str(i) for i in known_task_ids}
    removed = 0
    for sub in results_root.iterdir():
        if not sub.is_dir():
            continue
        if sub.name not in known:
            try:
                shutil.rmtree(sub, ignore_errors=True)
                removed += 1
            except OSError:
                pass
    if removed:
        logger.info("[DiskMaint] 清理孤立结果目录 %d 个", removed)
    return removed
