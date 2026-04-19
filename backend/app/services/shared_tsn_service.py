# -*- coding: utf-8 -*-
"""平台共享文件：上传、列表、元数据、过期清理、试验架次"""
import asyncio
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import UPLOAD_DIR, SHARED_TSN_RETENTION_DAYS, MAX_UPLOAD_SIZE, VIDEO_TRANSCODE_HEVC
from ..constants.shared_platform_assets import (
    VIDEO_EXTS,
    VALID_ASSET_KEYS,
    validate_extension_for_asset,
)
from ..models import SharedSortie, SharedTsnFile
from .video_web_transcode import (
    ffprobe_primary_video_codec,
    is_hevc_codec,
    transcode_hevc_file_to_browser_mp4,
)

logger = logging.getLogger(__name__)

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
        # 无过期文件时不要清理「尚无上传文件」的架次，否则用户新建架次后首次上传会先被此处误删
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
    await _purge_empty_sorties(db)
    return len(rows)


async def _purge_empty_sorties(db: AsyncSession) -> None:
    """在因过期删除了文件之后调用：删除因此变为无文件的架次（不用于清理用户刚建、尚未上传的架次）。"""
    r = await db.execute(select(SharedSortie.id))
    ids = list(r.scalars().all())
    removed = 0
    for sid in ids:
        cnt = (
            await db.execute(
                select(func.count(SharedTsnFile.id)).where(SharedTsnFile.sortie_id == sid)
            )
        ).scalar_one()
        if int(cnt or 0) == 0:
            await db.execute(delete(SharedSortie).where(SharedSortie.id == sid))
            removed += 1
    if removed:
        await db.commit()
        print(f"[SharedTsn] 已清理空架次 {removed} 条")


async def get_shared_by_id(db: AsyncSession, sid: int) -> Optional[SharedTsnFile]:
    r = await db.execute(select(SharedTsnFile).where(SharedTsnFile.id == sid))
    return r.scalar_one_or_none()


async def list_shared_files(db: AsyncSession) -> List[SharedTsnFile]:
    r = await db.execute(
        select(SharedTsnFile).order_by(SharedTsnFile.created_at.desc())
    )
    return list(r.scalars().all())


async def list_sorties_with_files(db: AsyncSession) -> List[SharedSortie]:
    r = await db.execute(
        select(SharedSortie)
        .options(selectinload(SharedSortie.files))
        .order_by(SharedSortie.created_at.desc())
    )
    return list(r.scalars().unique().all())


async def create_sortie(
    db: AsyncSession,
    *,
    sortie_label: str,
    experiment_date: Optional[date],
    remarks: Optional[str],
    uploaded_by_id: Optional[int],
) -> SharedSortie:
    row = SharedSortie(
        sortie_label=sortie_label.strip(),
        experiment_date=experiment_date,
        remarks=remarks.strip() if remarks else None,
        uploaded_by_id=uploaded_by_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_sortie_meta(
    db: AsyncSession,
    row: SharedSortie,
    *,
    sortie_label: Optional[str] = None,
    experiment_date: Optional[date] = None,
    remarks: Optional[str] = None,
    patch_keys: Optional[Set[str]] = None,
) -> SharedSortie:
    if patch_keys is not None:
        if "sortie_label" in patch_keys and sortie_label is not None:
            row.sortie_label = sortie_label.strip()
        if "experiment_date" in patch_keys:
            row.experiment_date = experiment_date
        if "remarks" in patch_keys:
            row.remarks = remarks.strip() if remarks else None
    await db.commit()
    await db.refresh(row)
    return row


async def delete_sortie_cascade(db: AsyncSession, row: SharedSortie) -> None:
    sid = row.id
    files_r = await db.execute(select(SharedTsnFile).where(SharedTsnFile.sortie_id == sid))
    for f in list(files_r.scalars().all()):
        await delete_shared(db, f)
    await db.execute(delete(SharedSortie).where(SharedSortie.id == sid))
    await db.commit()


async def get_sortie_by_id(db: AsyncSession, sid: int) -> Optional[SharedSortie]:
    r = await db.execute(select(SharedSortie).where(SharedSortie.id == sid))
    return r.scalar_one_or_none()


def _should_transcode_hevc_for_web(
    filename: str,
    asset_type: Optional[str],
    legacy_flat: bool,
) -> bool:
    """仅对架次视频类上传尝试 HEVC→H.264（依赖 ffprobe/ffmpeg）。"""
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in VIDEO_EXTS:
        return False
    if legacy_flat:
        return True
    return bool(asset_type and asset_type.startswith("video_"))


async def create_shared_from_upload(
    db: AsyncSession,
    *,
    filename: str,
    file_bytes: bytes,
    uploaded_by_id: Optional[int],
    sortie_id: Optional[int] = None,
    asset_type: Optional[str] = None,
    legacy_flat: bool = False,
) -> SharedTsnFile:
    """上传平台共享文件。

    - 新版：必须提供 sortie_id 与 asset_type（且在合法枚举内）。
    - legacy_flat=True：沿用旧逻辑，不要求架次（仅兼容旧客户端）。
    """
    if legacy_flat:
        ext = Path(filename).suffix.lower()
        from ..config import ALLOWED_EXTENSIONS

        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型，允许: {ALLOWED_EXTENSIONS}")
    else:
        if not sortie_id:
            raise ValueError("请选择试验架次")
        if not asset_type or asset_type not in VALID_ASSET_KEYS:
            raise ValueError("请选择数据类型")
        validate_extension_for_asset(filename, asset_type)

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError("文件超过大小限制")

    stored = f"{uuid.uuid4().hex}_{Path(filename).name}"
    dest = shared_storage_dir() / stored
    dest.write_bytes(file_bytes)

    vp_status = None
    vp_progress = None
    vp_err = None

    if _should_transcode_hevc_for_web(filename, asset_type, legacy_flat) and VIDEO_TRANSCODE_HEVC:
        codec = await asyncio.to_thread(ffprobe_primary_video_codec, dest)
        if is_hevc_codec(codec):
            ffmpeg_ok = bool(shutil.which("ffmpeg") or os.environ.get("FFMPEG_PATH"))
            if ffmpeg_ok:
                vp_status = "transcoding"
                vp_progress = 5
            else:
                vp_status = "failed"
                vp_progress = 0
                vp_err = "服务器未安装 ffmpeg，无法将 HEVC 转为浏览器可播的 H.264"
        else:
            vp_status = "ready"
            vp_progress = 100

    is_video_row = (asset_type and asset_type.startswith("video_")) or (
        legacy_flat and Path(filename).suffix.lower().lstrip(".") in VIDEO_EXTS
    )
    if vp_status is None and is_video_row:
        vp_status = "ready"
        vp_progress = 100

    sortie = await get_sortie_by_id(db, sortie_id) if sortie_id else None
    if sortie_id and not sortie:
        dest.unlink(missing_ok=True)
        raise ValueError("试验架次不存在")

    row = SharedTsnFile(
        original_filename=Path(filename).name,
        file_path=str(dest.resolve()),
        uploaded_by_id=uploaded_by_id,
        experiment_date=sortie.experiment_date if sortie else None,
        experiment_label=None,
        sortie_id=sortie_id,
        asset_type=asset_type if not legacy_flat else None,
        video_processing_status=vp_status,
        video_processing_progress=vp_progress,
        video_processing_error=vp_err,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def run_hevc_transcode_job(shared_id: int) -> None:
    """后台将 HEVC 转为 H.264；上传接口快速返回后再执行。"""
    from ..database import async_session

    async with async_session() as db:
        row = await get_shared_by_id(db, shared_id)
        if not row or row.video_processing_status != "transcoding":
            return
        path = Path(row.file_path)
        if not path.is_file():
            row.video_processing_status = "failed"
            row.video_processing_error = "上传文件不存在"
            row.video_processing_progress = 0
            await db.commit()
            return

        row.video_processing_progress = 10
        await db.commit()

        try:
            new_path = await asyncio.to_thread(transcode_hevc_file_to_browser_mp4, path)
            row.video_processing_progress = 85
            await db.commit()

            row.file_path = str(Path(new_path).resolve())
            codec = await asyncio.to_thread(ffprobe_primary_video_codec, Path(row.file_path))
            if is_hevc_codec(codec):
                row.video_processing_status = "failed"
                row.video_processing_error = "转码未完成，输出仍为 HEVC 或无法解码"
                row.video_processing_progress = 0
            else:
                row.video_processing_status = "ready"
                row.video_processing_progress = 100
                row.video_processing_error = None
        except Exception as e:
            logger.exception("run_hevc_transcode_job failed shared_id=%s", shared_id)
            row.video_processing_status = "failed"
            row.video_processing_error = str(e)[:800]
            row.video_processing_progress = 0
        await db.commit()


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


def asset_label_for_key(key: Optional[str]) -> Optional[str]:
    from ..constants.shared_platform_assets import list_asset_kind_options

    if not key:
        return None
    for item in list_asset_kind_options():
        if item["key"] == key:
            return item["label"]
    return key
