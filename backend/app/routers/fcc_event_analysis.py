# -*- coding: utf-8 -*-
"""飞控事件分析路由"""
import io
import uuid
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

from ..database import get_db
from ..deps import get_current_user
from ..services import FccEventAnalysisService
from ..services import shared_tsn_service as shared_tsn_svc
from ..config import UPLOAD_DIR, MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS
from ..background_jobs import run_fcc_event_analysis_task_job
from ..task_executor import submit_process_job


router = APIRouter(
    prefix="/api/fcc-event-analysis",
    tags=["飞控事件分析"],
    dependencies=[Depends(get_current_user)],
)


# ========== Pydantic Schemas ==========

class FccTaskResponse(BaseModel):
    id: int
    parse_task_id: Optional[int] = None
    pcap_filename: Optional[str] = None
    name: Optional[str] = None
    rule_template: str
    status: str
    progress: int = 0
    error_message: Optional[str] = None
    total_checks: int
    passed_checks: int
    failed_checks: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FccTaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[FccTaskResponse]


class FccCheckResultResponse(BaseModel):
    id: int
    sequence: int
    check_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    wireshark_filter: Optional[str] = None
    event_time: Optional[str] = None
    event_description: Optional[str] = None
    period_expected: Optional[str] = None
    period_actual: Optional[str] = None
    period_analysis: Optional[str] = None
    period_result: Optional[str] = None
    content_expected: Optional[str] = None
    content_actual: Optional[str] = None
    content_analysis: Optional[str] = None
    content_result: Optional[str] = None
    response_expected: Optional[str] = None
    response_actual: Optional[str] = None
    response_analysis: Optional[str] = None
    response_result: Optional[str] = None
    overall_result: str

    class Config:
        from_attributes = True


class FccCheckResultListResponse(BaseModel):
    total: int
    passed: int
    failed: int
    items: List[FccCheckResultResponse]


class FccTimelineEventResponse(BaseModel):
    id: int
    timestamp: float
    time_str: Optional[str] = None
    device: Optional[str] = None
    port: Optional[int] = None
    event_type: Optional[str] = None
    event_name: Optional[str] = None
    event_description: Optional[str] = None
    raw_data_hex: Optional[str] = None

    class Config:
        from_attributes = True


class FccTimelineListResponse(BaseModel):
    total: int
    items: List[FccTimelineEventResponse]


# ========== helpers ==========

def _task_to_response(task) -> FccTaskResponse:
    return FccTaskResponse(
        id=task.id,
        parse_task_id=task.parse_task_id,
        pcap_filename=task.pcap_filename,
        name=task.name,
        rule_template=task.rule_template,
        status=task.status,
        progress=getattr(task, "progress", None) or 0,
        error_message=task.error_message,
        total_checks=task.total_checks or 0,
        passed_checks=task.passed_checks or 0,
        failed_checks=task.failed_checks or 0,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def _check_to_response(r) -> FccCheckResultResponse:
    return FccCheckResultResponse(
        id=r.id,
        sequence=r.sequence,
        check_name=r.check_name,
        category=r.category,
        description=r.description,
        wireshark_filter=r.wireshark_filter,
        event_time=r.event_time,
        event_description=r.event_description,
        period_expected=r.period_expected,
        period_actual=r.period_actual,
        period_analysis=r.period_analysis,
        period_result=r.period_result,
        content_expected=r.content_expected,
        content_actual=r.content_actual,
        content_analysis=r.content_analysis,
        content_result=r.content_result,
        response_expected=r.response_expected,
        response_actual=r.response_actual,
        response_analysis=r.response_analysis,
        response_result=r.response_result,
        overall_result=r.overall_result,
    )


def _timeline_to_response(e) -> FccTimelineEventResponse:
    return FccTimelineEventResponse(
        id=e.id,
        timestamp=e.timestamp,
        time_str=e.time_str,
        device=e.device,
        port=e.port,
        event_type=e.event_type,
        event_name=e.event_name,
        event_description=e.event_description,
        raw_data_hex=e.raw_data_hex,
    )


# ========== Excel export helpers ==========

def _result_cn(v: Optional[str]) -> str:
    if not v:
        return ""
    m = {
        "detected": "已发生",
        "not_detected": "未发生",
        "na": "N/A",
        "pass": "通过",
        "fail": "失败",
        "warning": "警告",
        "pending": "待定",
    }
    return m.get(str(v).lower(), str(v))


def _check_row_dict(r) -> dict:
    return {
        "序号": r.sequence,
        "检查项": r.check_name or "",
        "分类": r.category or "",
        "描述": r.description or "",
        "事件时间": r.event_time or "",
        "事件描述": r.event_description or "",
        "检测详情": r.content_analysis or "",
        "检测状态": _result_cn(r.overall_result),
    }


def _timeline_row_dict(e) -> dict:
    return {
        "时间戳": e.timestamp,
        "时间": e.time_str or "",
        "设备": e.device or "",
        "端口": e.port if e.port is not None else "",
        "事件类型": e.event_type or "",
        "事件名称": e.event_name or "",
        "事件描述": e.event_description or "",
        "原始数据hex": e.raw_data_hex or "",
    }


_CHECK_COLS = ["序号", "检查项", "分类", "描述", "事件时间", "事件描述",
               "检测详情", "检测状态"]
_TL_COLS = ["时间戳", "时间", "设备", "端口", "事件类型", "事件名称", "事件描述", "原始数据hex"]


def _build_excel(results, timeline, overview_rows) -> bytes:
    overview_df = pd.DataFrame(overview_rows, columns=["项目", "值"])
    check_df = (
        pd.DataFrame([_check_row_dict(r) for r in results], columns=_CHECK_COLS)
        if results else pd.DataFrame(columns=_CHECK_COLS)
    )
    tl_df = (
        pd.DataFrame([_timeline_row_dict(e) for e in timeline], columns=_TL_COLS)
        if timeline else pd.DataFrame(columns=_TL_COLS)
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        overview_df.to_excel(writer, sheet_name="概览", index=False)
        check_df.to_excel(writer, sheet_name="检查结果", index=False)
        tl_df.to_excel(writer, sheet_name="时间线", index=False)
    buf.seek(0)
    return buf.read()


def _overview_rows(task):
    return [
        ("导出类型", "飞控事件分析"),
        ("任务ID", task.id),
        ("任务名称", task.name or ""),
        ("pcap文件", task.pcap_filename or ""),
        ("规则模板", task.rule_template or ""),
        ("状态", task.status or ""),
        ("检查项总数", task.total_checks or 0),
        ("通过", task.passed_checks or 0),
        ("失败", task.failed_checks or 0),
        ("创建时间", str(task.created_at) if task.created_at else ""),
        ("完成时间", str(task.completed_at) if task.completed_at else ""),
    ]


def _streaming_export(body: bytes, media_type: str, ascii_filename: str, utf8_filename: str):
    disp = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(utf8_filename)}'
    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={"Content-Disposition": disp},
    )


# ========== 路由接口 ==========

@router.post("/standalone/upload")
async def upload_standalone_pcap(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    divergence_tolerance_ms: int = Form(100),
    db: AsyncSession = Depends(get_db),
):
    """上传 pcap/pcapng，创建飞控事件分析任务并在后台执行。"""
    raw_name = file.filename or "capture.pcapng"
    suffix = Path(raw_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    tolerance = max(0, min(divergence_tolerance_ms, 200))

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件超过大小限制")

    sub = UPLOAD_DIR / "standalone_events"
    sub.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{raw_name}"
    dest = sub / stored_name
    dest.write_bytes(data)

    service = FccEventAnalysisService(db)
    task = await service.create_standalone_task(
        filename=raw_name,
        file_path=str(dest.resolve()),
    )
    background_tasks.add_task(
        submit_process_job, run_fcc_event_analysis_task_job, task.id, tolerance
    )

    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "message": f"已上传并开始飞控事件分析（分歧容忍 {tolerance}ms）",
    }


@router.post("/standalone/from-shared")
async def standalone_from_shared_pcap(
    background_tasks: BackgroundTasks,
    shared_tsn_id: int = Form(...),
    divergence_tolerance_ms: int = Form(100),
    db: AsyncSession = Depends(get_db),
):
    """使用平台共享 TSN 文件创建飞控事件分析（直接读取共享源文件，不复制）。"""
    row = await shared_tsn_svc.get_shared_by_id(db, shared_tsn_id)
    if not row:
        raise HTTPException(status_code=404, detail="平台共享数据不存在或已过期删除")
    suffix = Path(row.original_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="共享文件类型不支持")

    tolerance = max(0, min(divergence_tolerance_ms, 200))

    src = Path(row.file_path)
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"共享文件不存在: {row.file_path}")

    service = FccEventAnalysisService(db)
    task = await service.create_standalone_task(
        filename=row.original_filename,
        file_path=str(src.resolve()),
    )
    background_tasks.add_task(
        submit_process_job, run_fcc_event_analysis_task_job, task.id, tolerance
    )
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "message": f"已使用平台共享数据开始飞控事件分析（分歧容忍 {tolerance}ms）",
    }


@router.get("/standalone/tasks", response_model=FccTaskListResponse)
async def list_standalone_tasks(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    service = FccEventAnalysisService(db)
    items, total = await service.list_standalone_tasks(page=page, page_size=page_size)
    return FccTaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_task_to_response(t) for t in items],
    )


@router.get("/standalone/tasks/{task_id}", response_model=FccTaskResponse)
async def get_standalone_task(task_id: int, db: AsyncSession = Depends(get_db)):
    service = FccEventAnalysisService(db)
    task = await service.get_standalone_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="飞控事件分析任务不存在")
    return _task_to_response(task)


@router.get("/standalone/tasks/{task_id}/check-results", response_model=FccCheckResultListResponse)
async def get_standalone_check_results(task_id: int, db: AsyncSession = Depends(get_db)):
    service = FccEventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="飞控事件分析任务不存在")
    results = await service.get_check_results(task_id)
    passed = sum(1 for r in results if r.overall_result == "pass")
    failed = sum(1 for r in results if r.overall_result == "fail")
    return FccCheckResultListResponse(
        total=len(results),
        passed=passed,
        failed=failed,
        items=[_check_to_response(r) for r in results],
    )


@router.get("/standalone/tasks/{task_id}/check-results/{check_id}")
async def get_standalone_check_detail(task_id: int, check_id: int, db: AsyncSession = Depends(get_db)):
    service = FccEventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="飞控事件分析任务不存在")
    result = await service.get_check_result_detail(task_id, check_id)
    if not result:
        raise HTTPException(status_code=404, detail="检查项不存在")
    timeline_events = await service.get_timeline(task_id, check_id)
    return {
        "check_result": _check_to_response(result),
        "timeline_events": [_timeline_to_response(e) for e in timeline_events],
    }


@router.get("/standalone/tasks/{task_id}/timeline", response_model=FccTimelineListResponse)
async def get_standalone_timeline(task_id: int, db: AsyncSession = Depends(get_db)):
    service = FccEventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="飞控事件分析任务不存在")
    events = await service.get_timeline(task_id)
    return FccTimelineListResponse(
        total=len(events),
        items=[_timeline_to_response(e) for e in events],
    )


@router.get("/standalone/tasks/{task_id}/export")
async def export_fcc_event_analysis(task_id: int, db: AsyncSession = Depends(get_db)):
    """导出飞控事件分析结果 xlsx。"""
    service = FccEventAnalysisService(db)
    task = await service.get_standalone_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="飞控事件分析任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="分析未完成，无法导出")

    results = await service.get_check_results(task_id)
    timeline = await service.get_timeline(task_id)
    overview = _overview_rows(task)
    body = _build_excel(results, timeline, overview)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    ascii_fn = f"fcc_event_analysis_{task_id}.xlsx"
    utf8_fn = f"飞控事件分析_{task_id}.xlsx"
    return _streaming_export(body, media, ascii_fn, utf8_fn)
