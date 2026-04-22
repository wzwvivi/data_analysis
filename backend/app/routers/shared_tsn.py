# -*- coding: utf-8 -*-
"""平台共享数据（管理员上传，全员可选用）；按试验架次与数据种类管理。"""
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..constants.shared_platform_assets import VIDEO_EXTS, list_asset_kind_options
from ..database import get_db
from ..deps import get_current_user, get_current_user_media, require_admin
from ..models import (
    AircraftConfiguration,
    Protocol,
    ProtocolVersion,
    SharedSortie,
    SharedTsnFile,
    SoftwareConfiguration,
    User,
)
from ..services import shared_tsn_service as sts

router = APIRouter(prefix="/api/shared-tsn", tags=["平台共享TSN"])

_RANGE_HEADER = re.compile(r"bytes=(\d*)-(\d*)")


def _mime_for_path(path: Path) -> str:
    suf = path.suffix.lower()
    return {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
        ".m4v": "video/x-m4v",
        ".ts": "video/mp2t",
        ".pcapng": "application/octet-stream",
        ".pcap": "application/vnd.tcpdump.pcap",
        ".cap": "application/octet-stream",
    }.get(suf, "application/octet-stream")


class SharedTsnResponse(BaseModel):
    id: int
    original_filename: str
    experiment_date: Optional[str] = None
    experiment_label: Optional[str] = None
    sortie_id: Optional[int] = None
    sortie_label: Optional[str] = None
    asset_type: Optional[str] = None
    asset_label: Optional[str] = None
    created_at: Optional[str] = None
    video_processing_status: Optional[str] = None
    video_processing_progress: Optional[int] = None
    video_processing_error: Optional[str] = None

    class Config:
        from_attributes = True


class SharedTsnUpdate(BaseModel):
    experiment_date: Optional[date] = None
    experiment_label: Optional[str] = Field(None, max_length=500)


class SharedSortieCreate(BaseModel):
    sortie_label: str = Field(..., min_length=1, max_length=300)
    experiment_date: Optional[date] = None
    remarks: Optional[str] = Field(None, max_length=2000)
    aircraft_configuration_id: Optional[int] = None
    software_configuration_id: Optional[int] = None


class SharedSortieUpdate(BaseModel):
    sortie_label: Optional[str] = Field(None, min_length=1, max_length=300)
    experiment_date: Optional[date] = None
    remarks: Optional[str] = Field(None, max_length=2000)
    aircraft_configuration_id: Optional[int] = None
    software_configuration_id: Optional[int] = None


class AircraftConfigSummary(BaseModel):
    id: int
    name: str
    version: Optional[str] = None
    tsn_protocol_label: Optional[str] = None


class SoftwareConfigSummary(BaseModel):
    id: int
    name: str
    snapshot_date: Optional[str] = None


class SharedSortieResponse(BaseModel):
    id: int
    sortie_label: str
    experiment_date: Optional[str] = None
    remarks: Optional[str] = None
    created_at: Optional[str] = None
    aircraft_configuration_id: Optional[int] = None
    software_configuration_id: Optional[int] = None
    aircraft_configuration: Optional[AircraftConfigSummary] = None
    software_configuration: Optional[SoftwareConfigSummary] = None
    files: List[SharedTsnResponse] = []

    class Config:
        from_attributes = True


def _to_resp(row: SharedTsnFile, sortie_label: Optional[str] = None) -> SharedTsnResponse:
    return SharedTsnResponse(
        id=row.id,
        original_filename=row.original_filename,
        experiment_date=row.experiment_date.isoformat() if row.experiment_date else None,
        experiment_label=row.experiment_label,
        sortie_id=row.sortie_id,
        sortie_label=sortie_label,
        asset_type=row.asset_type,
        asset_label=sts.asset_label_for_key(row.asset_type),
        created_at=row.created_at.isoformat() if row.created_at else None,
        video_processing_status=row.video_processing_status,
        video_processing_progress=row.video_processing_progress,
        video_processing_error=row.video_processing_error,
    )


def _is_stream_video_transcoding(row: SharedTsnFile) -> bool:
    if row.video_processing_status != "transcoding":
        return False
    if row.asset_type and str(row.asset_type).startswith("video_"):
        return True
    ext = Path(row.original_filename).suffix.lower().lstrip(".")
    return ext in VIDEO_EXTS


async def _sortie_label_map(db: AsyncSession, sortie_ids: List[int]) -> Dict[int, str]:
    if not sortie_ids:
        return {}
    r = await db.execute(select(SharedSortie).where(SharedSortie.id.in_(sortie_ids)))
    return {s.id: s.sortie_label for s in r.scalars().all()}


async def _aircraft_summary(
    db: AsyncSession, cfg: Optional[AircraftConfiguration]
) -> Optional[AircraftConfigSummary]:
    if not cfg:
        return None
    label = None
    if cfg.tsn_protocol_version_id:
        r = await db.execute(
            select(ProtocolVersion, Protocol)
            .join(Protocol, Protocol.id == ProtocolVersion.protocol_id)
            .where(ProtocolVersion.id == cfg.tsn_protocol_version_id)
        )
        row = r.first()
        if row:
            pv, p = row
            label = f"{p.name} / {pv.version}"
    return AircraftConfigSummary(
        id=cfg.id, name=cfg.name, version=cfg.version, tsn_protocol_label=label
    )


def _software_summary(
    cfg: Optional[SoftwareConfiguration],
) -> Optional[SoftwareConfigSummary]:
    if not cfg:
        return None
    return SoftwareConfigSummary(
        id=cfg.id,
        name=cfg.name,
        snapshot_date=cfg.snapshot_date.isoformat() if cfg.snapshot_date else None,
    )


async def _sortie_to_resp(
    db: AsyncSession, s: SharedSortie, files: Optional[List[SharedTsnResponse]] = None
) -> SharedSortieResponse:
    return SharedSortieResponse(
        id=s.id,
        sortie_label=s.sortie_label,
        experiment_date=s.experiment_date.isoformat() if s.experiment_date else None,
        remarks=s.remarks,
        created_at=s.created_at.isoformat() if s.created_at else None,
        aircraft_configuration_id=s.aircraft_configuration_id,
        software_configuration_id=s.software_configuration_id,
        aircraft_configuration=await _aircraft_summary(db, s.aircraft_configuration),
        software_configuration=_software_summary(s.software_configuration),
        files=files or [],
    )


@router.get("/asset-kinds")
async def asset_kinds(_: User = Depends(get_current_user)):
    """可选的数据种类及允许的后缀（供上传表单）。"""
    return {"items": list_asset_kind_options()}


@router.head("/files/{shared_id}/stream")
async def head_shared_stream(
    shared_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user_media),
):
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    if _is_stream_video_transcoding(row):
        return Response(
            status_code=503,
            headers={"Retry-After": "5"},
        )
    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="物理文件不存在")
    size = path.stat().st_size
    return Response(
        headers={
            "Content-Length": str(size),
            "Accept-Ranges": "bytes",
            "Content-Type": _mime_for_path(path),
        }
    )


@router.get("/files/{shared_id}/stream")
async def stream_shared_file(
    shared_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user_media),
):
    """流式读取平台共享文件（支持 Range，便于浏览器 <video> 播放）。"""
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    if _is_stream_video_transcoding(row):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "视频正在服务端转码为 H.264（兼容浏览器），请稍后重试",
                "code": "video_transcoding",
            },
            headers={"Retry-After": "5"},
        )
    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="物理文件不存在")
    size = path.stat().st_size
    media = _mime_for_path(path)
    rng = request.headers.get("range") or request.headers.get("Range")
    if rng:
        m = _RANGE_HEADER.match(rng.strip())
        if not m:
            return Response(status_code=416)
        start_s, end_s = m.group(1), m.group(2)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            return Response(status_code=416)
        length = end - start + 1

        def iter_range():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Cache-Control": "private, max-age=3600",
        }
        return StreamingResponse(
            iter_range(), status_code=206, media_type=media, headers=headers
        )

    def iter_full():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        iter_full(),
        media_type=media,
        headers={
            "Content-Length": str(size),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/sorties", response_model=List[SharedSortieResponse])
async def list_sorties_tree(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """按试验架次分组的完整树（架次含文件列表）。"""
    sorties = await sts.list_sorties_with_files(db)
    loose: List[SharedTsnFile] = []
    r_loose = await db.execute(
        select(SharedTsnFile).where(SharedTsnFile.sortie_id.is_(None)).order_by(SharedTsnFile.created_at.desc())
    )
    loose = list(r_loose.scalars().all())
    out: List[SharedSortieResponse] = []
    for s in sorties:
        files = [_to_resp(f, s.sortie_label) for f in (s.files or [])]
        files.sort(key=lambda x: x.id, reverse=True)
        out.append(await _sortie_to_resp(db, s, files))
    if loose:
        unmapped = [_to_resp(f, None) for f in loose]
        out.append(
            SharedSortieResponse(
                id=0,
                sortie_label="未关联架次（历史数据）",
                experiment_date=None,
                remarks="升级平台前的上传记录",
                created_at=None,
                files=unmapped,
            )
        )
    return out


@router.post("/sorties", response_model=SharedSortieResponse)
async def create_sortie(
    body: SharedSortieCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = await sts.create_sortie(
        db,
        sortie_label=body.sortie_label,
        experiment_date=body.experiment_date,
        remarks=body.remarks,
        uploaded_by_id=admin.id,
        aircraft_configuration_id=body.aircraft_configuration_id,
        software_configuration_id=body.software_configuration_id,
    )
    r = await db.execute(
        select(SharedSortie)
        .options(
            selectinload(SharedSortie.aircraft_configuration),
            selectinload(SharedSortie.software_configuration),
        )
        .where(SharedSortie.id == row.id)
    )
    row = r.scalar_one()
    return await _sortie_to_resp(db, row, [])


@router.patch("/sorties/{sortie_id}", response_model=SharedSortieResponse)
async def update_sortie(
    sortie_id: int,
    body: SharedSortieUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await sts.get_sortie_by_id(db, sortie_id)
    if not row or sortie_id <= 0:
        raise HTTPException(status_code=404, detail="架次不存在")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    row = await sts.update_sortie_meta(
        db,
        row,
        sortie_label=patch.get("sortie_label"),
        experiment_date=patch.get("experiment_date"),
        remarks=patch.get("remarks"),
        aircraft_configuration_id=patch.get("aircraft_configuration_id"),
        software_configuration_id=patch.get("software_configuration_id"),
        patch_keys=set(patch.keys()),
    )
    sorties = await sts.list_sorties_with_files(db)
    for s in sorties:
        if s.id == row.id:
            return await _sortie_to_resp(
                db, s, [_to_resp(f, s.sortie_label) for f in (s.files or [])]
            )
    return await _sortie_to_resp(db, row, [])


@router.delete("/sorties/{sortie_id}")
async def delete_sortie(
    sortie_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if sortie_id <= 0:
        raise HTTPException(status_code=400, detail="无效架次")
    row = await sts.get_sortie_by_id(db, sortie_id)
    if not row:
        raise HTTPException(status_code=404, detail="架次不存在")
    await sts.delete_sortie_cascade(db, row)
    return {"success": True}


@router.get("", response_model=List[SharedTsnResponse])
async def list_shared(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """扁平列表（兼容各业务页下拉框）；含架次名称与数据种类。"""
    rows = await sts.list_shared_files(db)
    ids = list({r.sortie_id for r in rows if r.sortie_id})
    smap = await _sortie_label_map(db, ids)
    return [_to_resp(r, smap.get(r.sortie_id)) for r in rows]


@router.post("/upload")
async def upload_shared(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    sortie_id: Optional[int] = Form(None),
    asset_type: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    raw = file.filename or "capture.pcapng"
    data = await file.read()
    legacy = sortie_id is None and asset_type is None
    try:
        await sts.purge_expired_shared_files(db)
        row = await sts.create_shared_from_upload(
            db,
            filename=raw,
            file_bytes=data,
            uploaded_by_id=admin.id,
            sortie_id=sortie_id,
            asset_type=asset_type,
            legacy_flat=legacy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row.video_processing_status == "transcoding":
        background_tasks.add_task(sts.run_hevc_transcode_job, row.id)
    smap = await _sortie_label_map(db, [row.sortie_id] if row.sortie_id else [])
    msg = "已上传至平台共享库"
    if row.video_processing_status == "transcoding":
        msg = "已上传，视频正在后台转码为 H.264（浏览器可播），请稍候刷新列表"
    elif row.video_processing_status == "failed" and row.video_processing_error:
        msg = f"上传已保存：{row.video_processing_error}"
    return {
        "success": True,
        "id": row.id,
        "message": msg,
        "item": _to_resp(row, smap.get(row.sortie_id)),
        "video_job": {
            "status": row.video_processing_status,
            "progress": row.video_processing_progress or 0,
            "error": row.video_processing_error,
        },
    }


@router.get("/files/{shared_id}/video-job")
async def shared_video_job_status(
    shared_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """轮询 HEVC→H.264 转码进度（任意登录用户可读，便于工作台）。"""
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {
        "status": row.video_processing_status,
        "progress": row.video_processing_progress or 0,
        "error": row.video_processing_error,
    }


@router.patch("/{shared_id}", response_model=SharedTsnResponse)
async def update_shared(
    shared_id: int,
    body: SharedTsnUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="无更新字段")
    row = await sts.update_shared_meta(
        db,
        row,
        experiment_date=patch.get("experiment_date"),
        experiment_label=patch.get("experiment_label"),
        patch_keys=set(patch.keys()),
    )
    smap = await _sortie_label_map(db, [row.sortie_id] if row.sortie_id else [])
    return _to_resp(row, smap.get(row.sortie_id))


@router.delete("/{shared_id}")
async def delete_shared(
    shared_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = await sts.get_shared_by_id(db, shared_id)
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    await sts.delete_shared(db, row)
    return {"success": True}
