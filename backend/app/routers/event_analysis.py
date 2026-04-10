# -*- coding: utf-8 -*-
"""事件分析路由"""
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

from sqlalchemy import select

from ..database import get_db
from ..deps import get_current_user
from ..models import ParseTask
from ..services import EventAnalysisService
from ..services import shared_tsn_service as shared_tsn_svc
from ..config import UPLOAD_DIR, MAX_UPLOAD_SIZE, ALLOWED_EXTENSIONS
from ..background_jobs import (
    run_event_analysis_task_job,
    run_standalone_event_analysis_task_job,
)
from ..task_executor import submit_process_job


router = APIRouter(
    prefix="/api/event-analysis",
    tags=["事件分析"],
    dependencies=[Depends(get_current_user)],
)


# ========== Pydantic Schemas ==========

class EventAnalysisTaskResponse(BaseModel):
    """事件分析任务响应"""
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


class StandaloneTaskListResponse(BaseModel):
    """独立事件分析任务列表"""
    total: int
    page: int
    page_size: int
    items: List[EventAnalysisTaskResponse]


class EventCheckResultResponse(BaseModel):
    """检查结果响应"""
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


class EventTimelineEventResponse(BaseModel):
    """时间线事件响应"""
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


class CheckResultListResponse(BaseModel):
    """检查结果列表响应"""
    total: int
    passed: int
    failed: int
    items: List[EventCheckResultResponse]


class TimelineListResponse(BaseModel):
    """时间线列表响应"""
    total: int
    items: List[EventTimelineEventResponse]


def _result_cn(v: Optional[str]) -> str:
    if not v:
        return ""
    m = {"pass": "通过", "fail": "失败", "warning": "警告", "na": "N/A", "pending": "待定"}
    return m.get(str(v).lower(), str(v))


def _check_row_dict(r) -> dict:
    return {
        "序号": r.sequence,
        "检查项": r.check_name or "",
        "分类": r.category or "",
        "描述": r.description or "",
        "Wireshark过滤器": r.wireshark_filter or "",
        "事件时间": r.event_time or "",
        "事件描述": r.event_description or "",
        "周期_预期": r.period_expected or "",
        "周期_实际": r.period_actual or "",
        "周期_分析": r.period_analysis or "",
        "周期_结果": _result_cn(r.period_result),
        "内容_预期": r.content_expected or "",
        "内容_实际": r.content_actual or "",
        "内容_分析": r.content_analysis or "",
        "内容_结果": _result_cn(r.content_result),
        "响应_预期": r.response_expected or "",
        "响应_实际": r.response_actual or "",
        "响应_分析": r.response_analysis or "",
        "响应_结果": _result_cn(r.response_result),
        "综合结论": _result_cn(r.overall_result),
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
        "关联检查项ID": e.related_check_id if e.related_check_id is not None else "",
        "原始数据hex": e.raw_data_hex or "",
    }


def _overview_rows_linked(task, parse_task_id: int, parse_filename: str) -> List[tuple]:
    return [
        ("导出类型", "解析任务关联事件分析"),
        ("解析任务ID", parse_task_id),
        ("解析文件名", parse_filename or ""),
        ("事件分析任务ID", task.id),
        ("任务名称", task.name or ""),
        ("pcap/数据源", task.pcap_filename or parse_filename or ""),
        ("规则模板", task.rule_template or ""),
        ("状态", task.status or ""),
        ("检查项总数", task.total_checks or 0),
        ("通过", task.passed_checks or 0),
        ("失败", task.failed_checks or 0),
        ("创建时间", str(task.created_at) if task.created_at else ""),
        ("完成时间", str(task.completed_at) if task.completed_at else ""),
    ]


def _overview_rows_standalone(task) -> List[tuple]:
    return [
        ("导出类型", "独立事件分析"),
        ("事件分析任务ID", task.id),
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


_CHECK_EXPORT_COLS = [
    "序号", "检查项", "分类", "描述", "Wireshark过滤器", "事件时间", "事件描述",
    "周期_预期", "周期_实际", "周期_分析", "周期_结果",
    "内容_预期", "内容_实际", "内容_分析", "内容_结果",
    "响应_预期", "响应_实际", "响应_分析", "响应_结果", "综合结论",
]
_TIMELINE_EXPORT_COLS = [
    "时间戳", "时间", "设备", "端口", "事件类型", "事件名称", "事件描述", "关联检查项ID", "原始数据hex",
]


def _build_event_analysis_excel(results, timeline, overview_rows: List[tuple]) -> bytes:
    overview_df = pd.DataFrame(overview_rows, columns=["项目", "值"])
    check_df = (
        pd.DataFrame([_check_row_dict(r) for r in results], columns=_CHECK_EXPORT_COLS)
        if results
        else pd.DataFrame(columns=_CHECK_EXPORT_COLS)
    )
    tl_df = (
        pd.DataFrame([_timeline_row_dict(e) for e in timeline], columns=_TIMELINE_EXPORT_COLS)
        if timeline
        else pd.DataFrame(columns=_TIMELINE_EXPORT_COLS)
    )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        overview_df.to_excel(writer, sheet_name="概览", index=False)
        check_df.to_excel(writer, sheet_name="检查结果", index=False)
        tl_df.to_excel(writer, sheet_name="时间线", index=False)
    buf.seek(0)
    return buf.read()


# ========== 路由接口 ==========

@router.post("/tasks/{parse_task_id}/run")
async def run_event_analysis(
    parse_task_id: int,
    background_tasks: BackgroundTasks,
    rule_template: str = "default_v1",
    db: AsyncSession = Depends(get_db)
):
    """
    运行事件分析
    
    基于已完成的解析任务，执行事件分析
    """
    service = EventAnalysisService(db)
    
    # 检查或创建分析任务
    task = await service.get_or_create_analysis_task(parse_task_id, rule_template)
    
    if not task:
        raise HTTPException(status_code=400, detail="解析任务不存在或未完成")
    
    # 如果任务正在处理中，返回当前状态
    if task.status == "processing":
        return {
            "success": True,
            "task_id": task.id,
            "status": task.status,
            "message": "分析任务正在执行中"
        }
    
    # 在后台执行分析
    background_tasks.add_task(
        submit_process_job, run_event_analysis_task_job, parse_task_id, rule_template
    )
    
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "message": "事件分析任务已创建，正在后台执行"
    }


@router.get("/tasks/{parse_task_id}", response_model=EventAnalysisTaskResponse)
async def get_analysis_task(
    parse_task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取事件分析任务状态"""
    service = EventAnalysisService(db)
    task = await service.get_analysis_task(parse_task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    
    return _task_to_response(task)


def _task_to_response(task) -> EventAnalysisTaskResponse:
    return EventAnalysisTaskResponse(
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


@router.post("/standalone/upload")
async def upload_standalone_pcap(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    rule_template: str = Form("default_v1"),
    db: AsyncSession = Depends(get_db),
):
    """上传 pcap/pcapng，创建独立事件分析任务并在后台执行。"""
    raw_name = file.filename or "capture.pcapng"
    suffix = Path(raw_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，允许: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件超过大小限制")

    sub = UPLOAD_DIR / "standalone_events"
    sub.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{raw_name}"
    dest = sub / stored_name
    dest.write_bytes(data)

    service = EventAnalysisService(db)
    task = await service.create_standalone_task(
        filename=raw_name,
        file_path=str(dest.resolve()),
        rule_template=rule_template,
    )
    background_tasks.add_task(
        submit_process_job, run_standalone_event_analysis_task_job, task.id
    )

    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "message": "已上传并开始事件分析",
    }


@router.post("/standalone/from-shared")
async def standalone_from_shared_pcap(
    background_tasks: BackgroundTasks,
    shared_tsn_id: int = Form(...),
    rule_template: str = Form("default_v1"),
    db: AsyncSession = Depends(get_db),
):
    """使用平台共享 TSN 文件创建独立事件分析（复制到 standalone_events 目录）。"""
    row = await shared_tsn_svc.get_shared_by_id(db, shared_tsn_id)
    if not row:
        raise HTTPException(status_code=404, detail="平台共享数据不存在或已过期删除")
    suffix = Path(row.original_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="共享文件类型不支持")

    sub = UPLOAD_DIR / "standalone_events"
    sub.mkdir(parents=True, exist_ok=True)
    try:
        dest, display_name = shared_tsn_svc.copy_shared_to_workdir(
            row, sub, "shared_evt"
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    service = EventAnalysisService(db)
    task = await service.create_standalone_task(
        filename=display_name,
        file_path=str(dest.resolve()),
        rule_template=rule_template,
    )
    background_tasks.add_task(
        submit_process_job, run_standalone_event_analysis_task_job, task.id
    )
    return {
        "success": True,
        "task_id": task.id,
        "status": "processing",
        "message": "已使用平台共享数据开始事件分析",
    }


@router.get("/standalone/tasks", response_model=StandaloneTaskListResponse)
async def list_standalone_tasks(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """独立事件分析任务列表"""
    service = EventAnalysisService(db)
    items, total = await service.list_standalone_tasks(page=page, page_size=page_size)
    return StandaloneTaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_task_to_response(t) for t in items],
    )


@router.get("/standalone/tasks/{task_id}", response_model=EventAnalysisTaskResponse)
async def get_standalone_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """独立事件分析任务状态"""
    service = EventAnalysisService(db)
    task = await service.get_standalone_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="独立事件分析任务不存在")
    return _task_to_response(task)


@router.get("/standalone/tasks/{task_id}/check-results", response_model=CheckResultListResponse)
async def get_standalone_check_results(task_id: int, db: AsyncSession = Depends(get_db)):
    service = EventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="独立事件分析任务不存在")
    results = await service.get_check_results_by_analysis_id(task_id)
    passed = sum(1 for r in results if r.overall_result == "pass")
    failed = sum(1 for r in results if r.overall_result == "fail")
    return CheckResultListResponse(
        total=len(results),
        passed=passed,
        failed=failed,
        items=[
            EventCheckResultResponse(
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
            for r in results
        ],
    )


@router.get("/standalone/tasks/{task_id}/check-results/{check_id}")
async def get_standalone_check_detail(task_id: int, check_id: int, db: AsyncSession = Depends(get_db)):
    service = EventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="独立事件分析任务不存在")
    result = await service.get_check_result_for_analysis_task(task_id, check_id)
    if not result:
        raise HTTPException(status_code=404, detail="检查项不存在")
    timeline_events = await service.get_timeline_by_analysis_id(task_id, check_id)
    return {
        "check_result": EventCheckResultResponse(
            id=result.id,
            sequence=result.sequence,
            check_name=result.check_name,
            category=result.category,
            description=result.description,
            wireshark_filter=result.wireshark_filter,
            event_time=result.event_time,
            event_description=result.event_description,
            period_expected=result.period_expected,
            period_actual=result.period_actual,
            period_analysis=result.period_analysis,
            period_result=result.period_result,
            content_expected=result.content_expected,
            content_actual=result.content_actual,
            content_analysis=result.content_analysis,
            content_result=result.content_result,
            response_expected=result.response_expected,
            response_actual=result.response_actual,
            response_analysis=result.response_analysis,
            response_result=result.response_result,
            overall_result=result.overall_result,
        ),
        "timeline_events": [
            EventTimelineEventResponse(
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
            for e in timeline_events
        ],
    }


@router.get("/standalone/tasks/{task_id}/timeline", response_model=TimelineListResponse)
async def get_standalone_timeline(task_id: int, db: AsyncSession = Depends(get_db)):
    service = EventAnalysisService(db)
    if not await service.get_standalone_task(task_id):
        raise HTTPException(status_code=404, detail="独立事件分析任务不存在")
    events = await service.get_timeline_by_analysis_id(task_id)
    return TimelineListResponse(
        total=len(events),
        items=[
            EventTimelineEventResponse(
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
            for e in events
        ],
    )


@router.get("/tasks/{parse_task_id}/check-results", response_model=CheckResultListResponse)
async def get_check_results(
    parse_task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取检查单结果列表"""
    service = EventAnalysisService(db)
    
    task = await service.get_analysis_task(parse_task_id)
    if not task:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    
    results = await service.get_check_results(parse_task_id)
    
    passed = sum(1 for r in results if r.overall_result == "pass")
    failed = sum(1 for r in results if r.overall_result == "fail")
    
    return CheckResultListResponse(
        total=len(results),
        passed=passed,
        failed=failed,
        items=[
            EventCheckResultResponse(
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
                overall_result=r.overall_result
            )
            for r in results
        ]
    )


@router.get("/tasks/{parse_task_id}/check-results/{check_id}")
async def get_check_result_detail(
    parse_task_id: int,
    check_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取单个检查项详情"""
    service = EventAnalysisService(db)

    result = await service.get_check_result_for_task(parse_task_id, check_id)
    if not result:
        raise HTTPException(status_code=404, detail="检查项不存在或不属于当前任务")
    
    # 获取相关的时间线事件
    timeline_events = await service.get_timeline_events(parse_task_id, check_id)
    
    return {
        "check_result": EventCheckResultResponse(
            id=result.id,
            sequence=result.sequence,
            check_name=result.check_name,
            category=result.category,
            description=result.description,
            wireshark_filter=result.wireshark_filter,
            event_time=result.event_time,
            event_description=result.event_description,
            period_expected=result.period_expected,
            period_actual=result.period_actual,
            period_analysis=result.period_analysis,
            period_result=result.period_result,
            content_expected=result.content_expected,
            content_actual=result.content_actual,
            content_analysis=result.content_analysis,
            content_result=result.content_result,
            response_expected=result.response_expected,
            response_actual=result.response_actual,
            response_analysis=result.response_analysis,
            response_result=result.response_result,
            overall_result=result.overall_result
        ),
        "timeline_events": [
            EventTimelineEventResponse(
                id=e.id,
                timestamp=e.timestamp,
                time_str=e.time_str,
                device=e.device,
                port=e.port,
                event_type=e.event_type,
                event_name=e.event_name,
                event_description=e.event_description,
                raw_data_hex=e.raw_data_hex
            )
            for e in timeline_events
        ]
    }


@router.get("/tasks/{parse_task_id}/timeline", response_model=TimelineListResponse)
async def get_timeline(
    parse_task_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取事件时间线"""
    service = EventAnalysisService(db)
    
    task = await service.get_analysis_task(parse_task_id)
    if not task:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    
    events = await service.get_timeline_events(parse_task_id)
    
    return TimelineListResponse(
        total=len(events),
        items=[
            EventTimelineEventResponse(
                id=e.id,
                timestamp=e.timestamp,
                time_str=e.time_str,
                device=e.device,
                port=e.port,
                event_type=e.event_type,
                event_name=e.event_name,
                event_description=e.event_description,
                raw_data_hex=e.raw_data_hex
            )
            for e in events
        ]
    )


def _streaming_export(body: bytes, media_type: str, ascii_filename: str, utf8_filename: str) -> StreamingResponse:
    disp = f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(utf8_filename)}'
    return StreamingResponse(
        io.BytesIO(body),
        media_type=media_type,
        headers={"Content-Disposition": disp},
    )


@router.get("/tasks/{parse_task_id}/export")
async def export_linked_event_analysis(
    parse_task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    导出解析任务关联的事件分析结果：单个 xlsx，含「概览」「检查结果」「时间线」三个工作表。
    """
    service = EventAnalysisService(db)
    task = await service.get_analysis_task(parse_task_id)
    if not task:
        raise HTTPException(status_code=404, detail="事件分析任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="分析未完成，无法导出")

    results = await service.get_check_results(parse_task_id)
    timeline = await service.get_timeline_events(parse_task_id)

    pr = await db.execute(select(ParseTask).where(ParseTask.id == parse_task_id))
    parse_row = pr.scalar_one_or_none()
    parse_filename = parse_row.filename if parse_row else ""

    overview = _overview_rows_linked(task, parse_task_id, parse_filename)
    body = _build_event_analysis_excel(results, timeline, overview)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    ascii_fn = f"event_analysis_parse_{parse_task_id}.xlsx"
    utf8_fn = f"事件分析_解析任务{parse_task_id}.xlsx"
    return _streaming_export(body, media, ascii_fn, utf8_fn)


@router.get("/standalone/tasks/{task_id}/export")
async def export_standalone_event_analysis(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """导出独立事件分析任务：单个 xlsx，三个工作表（概览 / 检查结果 / 时间线）。"""
    service = EventAnalysisService(db)
    task = await service.get_standalone_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="独立事件分析任务不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="分析未完成，无法导出")

    results = await service.get_check_results_by_analysis_id(task_id)
    timeline = await service.get_timeline_by_analysis_id(task_id)
    overview = _overview_rows_standalone(task)
    body = _build_event_analysis_excel(results, timeline, overview)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    ascii_fn = f"event_analysis_standalone_{task_id}.xlsx"
    utf8_fn = f"事件分析_独立任务{task_id}.xlsx"
    return _streaming_export(body, media, ascii_fn, utf8_fn)
