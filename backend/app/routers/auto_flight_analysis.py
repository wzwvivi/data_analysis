# -*- coding: utf-8 -*-
"""自动飞行性能分析路由"""
import io
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..background_jobs import run_auto_flight_analysis_task_job
from ..config import ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE, UPLOAD_DIR
from ..database import get_db
from ..deps import get_current_user
from ..services import AutoFlightAnalysisService
from ..services import shared_tsn_service as shared_tsn_svc
from ..task_executor import submit_process_job


router = APIRouter(
    prefix="/api/auto-flight-analysis",
    tags=["自动飞行性能分析"],
    dependencies=[Depends(get_current_user)],
)


class AutoFlightTaskResponse(BaseModel):
    id: int
    parse_task_id: Optional[int] = None
    pcap_filename: Optional[str] = None
    name: Optional[str] = None
    source_type: str
    status: str
    progress: int = 0
    error_message: Optional[str] = None
    touchdown_count: int = 0
    steady_count: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None
    # MR4：本次分析所用的 TSN 协议版本（bundle），用于审计展示
    bundle_version_id: Optional[int] = None
    bundle_version_label: Optional[str] = None

    class Config:
        from_attributes = True


class AutoFlightTaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AutoFlightTaskResponse]


def _task_to_resp(t, bundle_version_label: Optional[str] = None) -> AutoFlightTaskResponse:
    return AutoFlightTaskResponse(
        id=t.id,
        parse_task_id=t.parse_task_id,
        pcap_filename=t.pcap_filename,
        name=t.name,
        source_type=t.source_type or "standalone",
        status=t.status,
        progress=t.progress or 0,
        error_message=t.error_message,
        touchdown_count=t.touchdown_count or 0,
        steady_count=t.steady_count or 0,
        created_at=t.created_at,
        completed_at=t.completed_at,
        bundle_version_id=getattr(t, "bundle_version_id", None),
        bundle_version_label=bundle_version_label,
    )


async def _resolve_bundle_version_label(db: AsyncSession, version_id: Optional[int]) -> Optional[str]:
    if not version_id:
        return None
    from sqlalchemy import select as _select
    from ..models import ProtocolVersion
    res = await db.execute(_select(ProtocolVersion.version).where(ProtocolVersion.id == int(version_id)))
    row = res.first()
    return row[0] if row else None


async def _build_label_map(db: AsyncSession, tasks) -> dict:
    vids = {int(t.bundle_version_id) for t in tasks if getattr(t, "bundle_version_id", None)}
    if not vids:
        return {}
    from sqlalchemy import select as _select
    from ..models import ProtocolVersion
    res = await db.execute(
        _select(ProtocolVersion.id, ProtocolVersion.version)
        .where(ProtocolVersion.id.in_(vids))
    )
    return {int(r[0]): r[1] for r in res.all()}


@router.post("/standalone/upload")
async def upload_standalone(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    bundle_version_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """上传 pcap/pcapng 并启动自动飞行性能分析。

    - `bundle_version_id`（可选，MR4）：本次分析绑定的 TSN 协议版本，仅用于
      审计展示（当前分析使用固定端口，不消费 bundle 内容）。
    """
    raw_name = file.filename or "capture.pcapng"
    suffix = Path(raw_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件超过大小限制")

    sub = UPLOAD_DIR / "auto_flight"
    sub.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{raw_name}"
    dest = sub / stored_name
    dest.write_bytes(data)

    service = AutoFlightAnalysisService(db)
    task = await service.create_task_from_pcap(
        raw_name,
        str(dest.resolve()),
        source_type="standalone",
        bundle_version_id=bundle_version_id,
    )
    background_tasks.add_task(submit_process_job, run_auto_flight_analysis_task_job, task.id)
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "bundle_version_id": task.bundle_version_id,
        "message": "已开始自动飞行性能分析",
    }


@router.post("/standalone/from-shared")
async def from_shared(
    background_tasks: BackgroundTasks,
    shared_tsn_id: int = Form(...),
    bundle_version_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """使用平台共享 TSN 文件创建自动飞行性能分析（直接读取共享源文件，不复制）。"""
    row = await shared_tsn_svc.get_shared_by_id(db, shared_tsn_id)
    if not row:
        raise HTTPException(status_code=404, detail="平台共享数据不存在或已过期删除")
    suffix = Path(row.original_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="共享文件类型不支持")

    src = Path(row.file_path)
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"共享文件不存在: {row.file_path}")

    service = AutoFlightAnalysisService(db)
    task = await service.create_task_from_pcap(
        row.original_filename,
        str(src.resolve()),
        source_type="shared",
        bundle_version_id=bundle_version_id,
    )
    background_tasks.add_task(submit_process_job, run_auto_flight_analysis_task_job, task.id)
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "bundle_version_id": task.bundle_version_id,
        "message": "已使用平台共享数据开始自动飞行性能分析",
    }


@router.post("/from-parse-task")
async def from_parse_task(
    background_tasks: BackgroundTasks,
    parse_task_id: int = Form(...),
    bundle_version_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """基于已有解析任务启动自动飞行性能分析。

    `bundle_version_id` 省略时默认继承 ParseTask.protocol_version_id。
    """
    service = AutoFlightAnalysisService(db)
    task = await service.create_task_from_parse(
        parse_task_id, bundle_version_id=bundle_version_id
    )
    background_tasks.add_task(submit_process_job, run_auto_flight_analysis_task_job, task.id)
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "bundle_version_id": task.bundle_version_id,
        "message": f"已基于解析任务#{parse_task_id}开始自动飞行性能分析",
    }


@router.get("/tasks", response_model=AutoFlightTaskListResponse)
async def list_tasks(page: int = 1, page_size: int = 20, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    items, total = await service.list_tasks(page=page, page_size=page_size)
    label_map = await _build_label_map(db, items)
    return AutoFlightTaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            _task_to_resp(
                x,
                bundle_version_label=label_map.get(int(x.bundle_version_id)) if x.bundle_version_id else None,
            )
            for x in items
        ],
    )


@router.get("/tasks/{task_id}", response_model=AutoFlightTaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    label = await _resolve_bundle_version_label(db, task.bundle_version_id)
    return _task_to_resp(task, bundle_version_label=label)


@router.get("/tasks/{task_id}/touchdowns")
async def get_touchdowns(task_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    if not await service.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    items = await service.get_touchdowns(task_id)
    return {
        "total": len(items),
        "items": [
            {
                "id": x.id,
                "sequence": x.sequence,
                "touchdown_ts": x.touchdown_ts,
                "touchdown_time": x.touchdown_time,
                "irs1_vz": x.irs1_vz,
                "irs2_vz": x.irs2_vz,
                "irs3_vz": x.irs3_vz,
                "vz_spread": x.vz_spread,
                "irs1_az_peak": x.irs1_az_peak,
                "irs2_az_peak": x.irs2_az_peak,
                "irs3_az_peak": x.irs3_az_peak,
                "az_peak_spread": x.az_peak_spread,
                "rating": x.rating,
                "summary": x.summary,
            }
            for x in items
        ],
    }


@router.get("/tasks/{task_id}/touchdowns/{td_id}")
async def get_touchdown_detail(task_id: int, td_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    if not await service.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    items = await service.get_touchdowns(task_id)
    row = next((x for x in items if x.id == td_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="触底分析记录不存在")
    return {
        "id": row.id,
        "sequence": row.sequence,
        "touchdown_time": row.touchdown_time,
        "summary": row.summary,
        "rating": row.rating,
        "chart_data": row.chart_data or {},
    }


@router.get("/tasks/{task_id}/steady-states")
async def get_steady_states(task_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    if not await service.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    items = await service.get_steady_states(task_id)
    return {
        "total": len(items),
        "items": [
            {
                "id": x.id,
                "sequence": x.sequence,
                "start_time": x.start_time,
                "end_time": x.end_time,
                "duration_s": x.duration_s,
                "mode_label": x.mode_label,
                "alt_bias": x.alt_bias,
                "alt_rms": x.alt_rms,
                "alt_max_abs": x.alt_max_abs,
                "lat_bias": x.lat_bias,
                "lat_rms": x.lat_rms,
                "lat_max_abs": x.lat_max_abs,
                "spd_bias": x.spd_bias,
                "spd_rms": x.spd_rms,
                "spd_max_abs": x.spd_max_abs,
                "rating": x.rating,
                "summary": x.summary,
            }
            for x in items
        ],
    }


@router.get("/tasks/{task_id}/steady-states/{ss_id}")
async def get_steady_state_detail(task_id: int, ss_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    if not await service.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    items = await service.get_steady_states(task_id)
    row = next((x for x in items if x.id == ss_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="稳态分析记录不存在")
    return {
        "id": row.id,
        "sequence": row.sequence,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "summary": row.summary,
        "rating": row.rating,
        "chart_data": row.chart_data or {},
    }


@router.get("/tasks/{task_id}/export")
async def export_results(task_id: int, db: AsyncSession = Depends(get_db)):
    service = AutoFlightAnalysisService(db)
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="分析未完成，无法导出")

    touchdowns = await service.get_touchdowns(task_id)
    steady = await service.get_steady_states(task_id)
    overview_rows = [
        ("导出类型", "自动飞行性能分析"),
        ("任务ID", task.id),
        ("任务名称", task.name or ""),
        ("来源类型", task.source_type or ""),
        ("触底次数", task.touchdown_count or 0),
        ("稳态段数", task.steady_count or 0),
        ("状态", task.status or ""),
        ("创建时间", str(task.created_at) if task.created_at else ""),
        ("完成时间", str(task.completed_at) if task.completed_at else ""),
    ]

    overview_df = pd.DataFrame(overview_rows, columns=["项目", "值"])
    td_df = pd.DataFrame(
        [
            {
                "序号": x.sequence,
                "触底时间": x.touchdown_time or "",
                "IRS1垂直速度": x.irs1_vz,
                "IRS2垂直速度": x.irs2_vz,
                "IRS3垂直速度": x.irs3_vz,
                "垂直速度三机差值": x.vz_spread,
                "IRS1过载峰值": x.irs1_az_peak,
                "IRS2过载峰值": x.irs2_az_peak,
                "IRS3过载峰值": x.irs3_az_peak,
                "过载峰值三机差值": x.az_peak_spread,
                "评级": x.rating,
                "摘要": x.summary or "",
            }
            for x in touchdowns
        ]
    )
    ss_df = pd.DataFrame(
        [
            {
                "序号": x.sequence,
                "起始时间": x.start_time or "",
                "结束时间": x.end_time or "",
                "持续时间(s)": x.duration_s,
                "高度偏差RMS": x.alt_rms,
                "水平偏差RMS": x.lat_rms,
                "速度偏差RMS": x.spd_rms,
                "评级": x.rating,
                "摘要": x.summary or "",
            }
            for x in steady
        ]
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        overview_df.to_excel(writer, sheet_name="概览", index=False)
        td_df.to_excel(writer, sheet_name="触底分析", index=False)
        ss_df.to_excel(writer, sheet_name="稳态分析", index=False)
    buf.seek(0)

    ascii_fn = f"auto_flight_analysis_{task.id}.xlsx"
    utf8_fn = f"自动飞行性能分析_{task.id}.xlsx"
    disp = f'attachment; filename="{ascii_fn}"; filename*=UTF-8\'\'{quote(utf8_fn)}'
    return StreamingResponse(
        io.BytesIO(buf.read()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disp},
    )
