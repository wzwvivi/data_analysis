# -*- coding: utf-8 -*-
"""平台共享 TSN 文件：上传、列表、元数据、过期清理"""
import shutil
import time
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional, Set, Tuple

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import UPLOAD_DIR, ALLOWED_EXTENSIONS, SHARED_TSN_RETENTION_DAYS, MAX_UPLOAD_SIZE
from ..models import SharedTsnFile


SHARED_SUBDIR = "shared_tsn"


def shared_storage_dir() -> Path:
    d = UPLOAD_DIR / SHARED_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


async def purge_expired_shared_files(db: AsyncSession) -> int:
    """删除创建时间早于保留期的记录及磁盘文件。"""
    cutoff = datetime.utcnow() - timedelta(days=SHARED_TSN_RETENTION_DAYS)
    r = await db.execute(select(SharedTsnFile).where(SharedTsnFile.created_at < cutoff))
    rows = list(r.scalars().all())
    if not rows:
        return 0
    paths = [row.file_path for row in rows]
    await db.execute(delete(SharedTsnFile).where(SharedTsnFile.created_at < cutoff))
    await db.commit()
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    print(f"[SharedTsn] 已清理过期共享文件 {len(rows)} 条（保留 {SHARED_TSN_RETENTION_DAYS} 天内）")
    return len(rows)


async def get_shared_by_id(db: AsyncSession, sid: int) -> Optional[SharedTsnFile]:
    r = await db.execute(select(SharedTsnFile).where(SharedTsnFile.id == sid))
    return r.scalar_one_or_none()


async def list_shared_files(db: AsyncSession) -> List[SharedTsnFile]:
    r = await db.execute(
        select(SharedTsnFile).order_by(SharedTsnFile.created_at.desc())
    )
    return list(r.scalars().all())


async def create_shared_from_upload(
    db: AsyncSession,
    *,
    filename: str,
    file_bytes: bytes,
    uploaded_by_id: Optional[int],
) -> SharedTsnFile:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不支持的文件类型，允许: {ALLOWED_EXTENSIONS}")
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError("文件超过大小限制")

    stored = f"{uuid.uuid4().hex}_{Path(filename).name}"
    dest = shared_storage_dir() / stored
    dest.write_bytes(file_bytes)

    row = SharedTsnFile(
        original_filename=Path(filename).name,
        file_path=str(dest.resolve()),
        uploaded_by_id=uploaded_by_id,
        experiment_date=None,
        experiment_label=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_shared_meta(
    db: AsyncSession,
    row: SharedTsnFile,
    *,
    experiment_date: Optional[date] = None,
    experiment_label: Optional[str] = None,
    patch_keys: Optional[Set[str]] = None,
) -> SharedTsnFile:
    if patch_keys is not None:
        if "experiment_date" in patch_keys:
            row.experiment_date = experiment_date
        if "experiment_label" in patch_keys:
            row.experiment_label = experiment_label
    else:
        if experiment_date is not None:
            row.experiment_date = experiment_date
        if experiment_label is not None:
            row.experiment_label = experiment_label
    await db.commit()
    await db.refresh(row)
    return row


async def delete_shared(db: AsyncSession, row: SharedTsnFile) -> None:
    pk = row.id
    try:
        Path(row.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    await db.execute(delete(SharedTsnFile).where(SharedTsnFile.id == pk))
    await db.commit()


def copy_shared_to_workdir(
    row: SharedTsnFile,
    dest_dir: Path,
    name_prefix: str,
) -> Tuple[Path, str]:
    """复制共享文件到任务目录，返回 (绝对路径, 展示用原始文件名)。"""
    src = Path(row.file_path)
    if not src.is_file():
        raise FileNotFoundError(f"共享文件不存在: {row.file_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    safe_name = f"{name_prefix}_{ts}_{row.original_filename}"
    dest = dest_dir / safe_name
    shutil.copy2(src, dest)
    return dest.resolve(), row.original_filename
