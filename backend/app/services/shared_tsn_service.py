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
    _is_browser_playable,
    ffprobe_primary_video_codec,
    is_hevc_codec,
    make_browser_playable,
    needs_browser_preprocess,
    transcode_hevc_file_to_browser_mp4,
)

logger = logging.getLogger(__name__)

SHARED_SUBDIR = "shared_tsn"

# 视频预处理队列 (ffmpeg): 串行执行, 避免多份 ffmpeg 同时吃满 CPU 把 pcap 解析/API 饿死。
# 默认 1; 若目标机更强可设 VIDEO_TRANSCODE_CONCURRENCY=2。
_VIDEO_CONCURRENCY = max(1, int(os.environ.get("VIDEO_TRANSCODE_CONCURRENCY", "1")))
_VIDEO_SEM: Optional[asyncio.Semaphore] = None


def _get_video_semaphore() -> asyncio.Semaphore:
    """惰性创建: 必须在 asyncio event loop 里才能实例化 Semaphore。"""
    global _VIDEO_SEM
    if _VIDEO_SEM is None:
        _VIDEO_SEM = asyncio.Semaphore(_VIDEO_CONCURRENCY)
    return _VIDEO_SEM


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
        .options(
            selectinload(SharedSortie.files),
            selectinload(SharedSortie.aircraft_configuration),
            selectinload(SharedSortie.software_configuration),
        )
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
    aircraft_configuration_id: Optional[int] = None,
    software_configuration_id: Optional[int] = None,
) -> SharedSortie:
    row = SharedSortie(
        sortie_label=sortie_label.strip(),
        experiment_date=experiment_date,
        remarks=remarks.strip() if remarks else None,
        uploaded_by_id=uploaded_by_id,
        aircraft_configuration_id=aircraft_configuration_id,
        software_configuration_id=software_configuration_id,
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
    aircraft_configuration_id: Optional[int] = None,
    software_configuration_id: Optional[int] = None,
    patch_keys: Optional[Set[str]] = None,
) -> SharedSortie:
    if patch_keys is not None:
        if "sortie_label" in patch_keys and sortie_label is not None:
            row.sortie_label = sortie_label.strip()
        if "experiment_date" in patch_keys:
            row.experiment_date = experiment_date
        if "remarks" in patch_keys:
            row.remarks = remarks.strip() if remarks else None
        if "aircraft_configuration_id" in patch_keys:
            row.aircraft_configuration_id = aircraft_configuration_id
        if "software_configuration_id" in patch_keys:
            row.software_configuration_id = software_configuration_id
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


def _validate_shared_upload_meta(
    *,
    filename: str,
    asset_type: Optional[str],
    legacy_flat: bool,
) -> None:
    """只校验文件名/资产类型；不碰字节流，便于先 validate 再落盘。"""
    if legacy_flat:
        ext = Path(filename).suffix.lower()
        from ..config import ALLOWED_EXTENSIONS

        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型，允许: {ALLOWED_EXTENSIONS}")
    else:
        if not asset_type or asset_type not in VALID_ASSET_KEYS:
            raise ValueError("请选择数据类型")
        validate_extension_for_asset(filename, asset_type)


def allocate_shared_storage_path(filename: str) -> Path:
    """为上传分配一个最终落盘路径（shared_storage_dir 下的 uuid 前缀名）。"""
    stored = f"{uuid.uuid4().hex}_{Path(filename).name}"
    return shared_storage_dir() / stored


async def create_shared_from_path(
    db: AsyncSession,
    *,
    filename: str,
    stored_path: Path,
    file_size: int,
    uploaded_by_id: Optional[int],
    sortie_id: Optional[int] = None,
    asset_type: Optional[str] = None,
    legacy_flat: bool = False,
) -> SharedTsnFile:
    """已落盘的文件入库；架次/资产类型校验失败会清理 stored_path。

    用于流式上传场景：router 先把请求体流式写到 ``stored_path``，再调用本函数。
    """
    try:
        _validate_shared_upload_meta(
            filename=filename, asset_type=asset_type, legacy_flat=legacy_flat
        )
        if not legacy_flat and not sortie_id:
            raise ValueError("请选择试验架次")
        if file_size > MAX_UPLOAD_SIZE:
            raise ValueError("文件超过大小限制")

        sortie = await get_sortie_by_id(db, sortie_id) if sortie_id else None
        if sortie_id and not sortie:
            raise ValueError("试验架次不存在")

        vp_status = None
        vp_progress = None
        vp_err = None

        if (
            _should_transcode_hevc_for_web(filename, asset_type, legacy_flat)
            and VIDEO_TRANSCODE_HEVC
        ):
            codec = await asyncio.to_thread(ffprobe_primary_video_codec, stored_path)
            # 入队条件放宽: 任何"容器/编码不被浏览器直接接受"的视频都进队列。
            # 成本: 多做了 .mkv/.avi/.ts 等的 remux 处理（秒级）。
            # 收益: 浏览器端不再出现"上传成功但播不了"的黑屏/白屏。
            if needs_browser_preprocess(stored_path, codec):
                ffmpeg_ok = bool(shutil.which("ffmpeg") or os.environ.get("FFMPEG_PATH"))
                if ffmpeg_ok:
                    vp_status = "transcoding"
                    vp_progress = 5
                else:
                    vp_status = "failed"
                    vp_progress = 0
                    if is_hevc_codec(codec):
                        vp_err = "服务器未安装 ffmpeg，无法将 HEVC 转为浏览器可播的 H.264"
                    else:
                        vp_err = "服务器未安装 ffmpeg，无法将该容器/编码转为浏览器可播"
            else:
                vp_status = "ready"
                vp_progress = 100

        is_video_row = (asset_type and asset_type.startswith("video_")) or (
            legacy_flat and Path(filename).suffix.lower().lstrip(".") in VIDEO_EXTS
        )
        if vp_status is None and is_video_row:
            vp_status = "ready"
            vp_progress = 100

        row = SharedTsnFile(
            original_filename=Path(filename).name,
            file_path=str(stored_path.resolve()),
            file_size=file_size,
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
    except Exception:
        # 入库失败则清理已落盘的临时文件，避免孤儿占用磁盘
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


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
    """兼容旧调用：仍接受整份 bytes。新 router 已改用流式版本 create_shared_from_path。"""
    _validate_shared_upload_meta(
        filename=filename, asset_type=asset_type, legacy_flat=legacy_flat
    )
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError("文件超过大小限制")

    dest = allocate_shared_storage_path(filename)
    dest.write_bytes(file_bytes)

    return await create_shared_from_path(
        db,
        filename=filename,
        stored_path=dest,
        file_size=len(file_bytes),
        uploaded_by_id=uploaded_by_id,
        sortie_id=sortie_id,
        asset_type=asset_type,
        legacy_flat=legacy_flat,
    )


async def run_hevc_transcode_job(shared_id: int) -> None:
    """后台预处理视频: 先 remux 快速通道, 不行再 libx264 重编码。

    实际策略见 ``video_web_transcode.make_browser_playable``。

    通过 ``_VIDEO_SEM`` 串行化, 避免多份 ffmpeg 同时跑把 CPU 打满。
    注意: 只有 "等到 semaphore + 实际跑 ffmpeg" 的那段才会阻塞, DB 事务不长时间持有。
    """
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

    # 重新开一个 session 跑 ffmpeg, 不要让 DB 事务跨过长时间 ffmpeg 调用。
    sem = _get_video_semaphore()
    try:
        async with sem:
            # 进入真正执行时更新进度, 让前端能看到"从排队到编码"的转换
            async with async_session() as db2:
                row2 = await get_shared_by_id(db2, shared_id)
                if row2 and row2.video_processing_status == "transcoding":
                    row2.video_processing_progress = 20
                    await db2.commit()
            new_path_raw = await asyncio.to_thread(make_browser_playable, path)
        new_path = Path(new_path_raw)
    except Exception as e:
        logger.exception("run_hevc_transcode_job ffmpeg failed shared_id=%s", shared_id)
        async with async_session() as db3:
            row3 = await get_shared_by_id(db3, shared_id)
            if row3:
                row3.video_processing_status = "failed"
                row3.video_processing_error = str(e)[:800]
                row3.video_processing_progress = 0
                await db3.commit()
        return

    async with async_session() as db4:
        row4 = await get_shared_by_id(db4, shared_id)
        if not row4:
            return
        row4.file_path = str(new_path.resolve())
        row4.video_processing_progress = 85
        await db4.commit()

        codec = await asyncio.to_thread(ffprobe_primary_video_codec, Path(row4.file_path))
        if _is_browser_playable(Path(row4.file_path), codec):
            row4.video_processing_status = "ready"
            row4.video_processing_progress = 100
            row4.video_processing_error = None
        else:
            row4.video_processing_status = "failed"
            row4.video_processing_progress = 0
            row4.video_processing_error = (
                f"预处理后仍不被浏览器识别 (codec={codec}, ext={new_path.suffix})"
            )
        await db4.commit()


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
