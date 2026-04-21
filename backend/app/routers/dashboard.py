# -*- coding: utf-8 -*-
"""平台总览仪表盘路由

聚合各业务模块的统计信息，供前端仪表盘页面展示。
所有查询均为只读且按常量上限保护，避免大数据量下的慢查询。
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import (
    AutoFlightAnalysisTask,
    CompareTask,
    FccEventAnalysisTask,
    FmsEventAnalysisTask,
    ParseResult,
    ParseTask,
    SharedTsnFile,
    User,
)
from ..models.arinc429 import Arinc429Device


FCC_RULE_TEMPLATE = "fcc_v1"
FM_RULE_TEMPLATE = "default_v1"


router = APIRouter(
    prefix="/api/dashboard",
    tags=["仪表盘"],
    dependencies=[Depends(get_current_user)],
)


# ========== Pydantic Schemas ==========

class StatusBreakdown(BaseModel):
    total: int = 0
    completed: int = 0
    processing: int = 0
    pending: int = 0
    failed: int = 0


class EventAnalysisSummary(BaseModel):
    total: int = 0
    completed: int = 0
    processing: int = 0
    failed: int = 0
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0


class AutoFlightSummary(BaseModel):
    total: int = 0
    completed: int = 0
    processing: int = 0
    failed: int = 0
    touchdown_count: int = 0
    steady_count: int = 0


class CompareSummary(BaseModel):
    total: int = 0
    completed: int = 0
    processing: int = 0
    failed: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0


class RecentParseTask(BaseModel):
    id: int
    filename: str
    status: str
    progress: int = 0
    parsed_packets: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DailyCount(BaseModel):
    date: str
    count: int


class OverviewResponse(BaseModel):
    generated_at: datetime
    users: dict
    parse_tasks: StatusBreakdown
    parse_results_total: int
    event_analysis: EventAnalysisSummary
    fcc_event_analysis: EventAnalysisSummary
    auto_flight_analysis: AutoFlightSummary
    compare_tasks: CompareSummary
    shared_tsn: dict
    protocol_devices_total: int
    recent_parse_tasks: List[RecentParseTask]
    parse_tasks_trend_7d: List[DailyCount]


# ========== Helpers ==========

def _merge_status_rows(rows) -> StatusBreakdown:
    breakdown = StatusBreakdown()
    for status, cnt in rows:
        cnt = int(cnt or 0)
        breakdown.total += cnt
        key = (status or "").lower()
        if key == "completed":
            breakdown.completed = cnt
        elif key == "processing":
            breakdown.processing = cnt
        elif key == "pending":
            breakdown.pending = cnt
        elif key == "failed":
            breakdown.failed = cnt
    return breakdown


async def _status_breakdown(db: AsyncSession, model) -> StatusBreakdown:
    r = await db.execute(select(model.status, func.count()).group_by(model.status))
    return _merge_status_rows(r.all())


async def _event_summary_for_model(db: AsyncSession, model) -> EventAnalysisSummary:
    """按拆分后的新表聚合事件分析统计（FMS / FCC 各走自己的表）。"""
    status_rows = await db.execute(
        select(model.status, func.count()).group_by(model.status)
    )
    sb = _merge_status_rows(status_rows.all())

    sums = await db.execute(
        select(
            func.coalesce(func.sum(model.total_checks), 0),
            func.coalesce(func.sum(model.passed_checks), 0),
            func.coalesce(func.sum(model.failed_checks), 0),
        )
    )
    total_checks, passed_checks, failed_checks = sums.one()

    return EventAnalysisSummary(
        total=sb.total,
        completed=sb.completed,
        processing=sb.processing,
        failed=sb.failed,
        total_checks=int(total_checks or 0),
        passed_checks=int(passed_checks or 0),
        failed_checks=int(failed_checks or 0),
    )


# ========== Endpoints ==========

@router.get("/overview", response_model=OverviewResponse)
async def get_overview(db: AsyncSession = Depends(get_db)):
    """获取平台总览信息。"""
    users_total = (
        await db.execute(select(func.count(User.id)))
    ).scalar_one() or 0
    admin_total = (
        await db.execute(
            select(func.count(User.id)).where(User.role == "admin")
        )
    ).scalar_one() or 0

    parse_breakdown = await _status_breakdown(db, ParseTask)
    parse_results_total = (
        await db.execute(select(func.count(ParseResult.id)))
    ).scalar_one() or 0

    fm_summary = await _event_summary_for_model(db, FmsEventAnalysisTask)
    fcc_summary = await _event_summary_for_model(db, FccEventAnalysisTask)

    af_breakdown = await _status_breakdown(db, AutoFlightAnalysisTask)
    af_sums = await db.execute(
        select(
            func.coalesce(func.sum(AutoFlightAnalysisTask.touchdown_count), 0),
            func.coalesce(func.sum(AutoFlightAnalysisTask.steady_count), 0),
        )
    )
    td_total, ss_total = af_sums.one()
    auto_flight = AutoFlightSummary(
        total=af_breakdown.total,
        completed=af_breakdown.completed,
        processing=af_breakdown.processing,
        failed=af_breakdown.failed,
        touchdown_count=int(td_total or 0),
        steady_count=int(ss_total or 0),
    )

    cmp_breakdown = await _status_breakdown(db, CompareTask)
    cmp_r = await db.execute(
        select(CompareTask.overall_result, func.count()).group_by(CompareTask.overall_result)
    )
    cmp_pass = cmp_warn = cmp_fail = 0
    for rst, cnt in cmp_r.all():
        rst = (rst or "").lower()
        cnt = int(cnt or 0)
        if rst == "pass":
            cmp_pass = cnt
        elif rst == "warning":
            cmp_warn = cnt
        elif rst == "fail":
            cmp_fail = cnt
    compare_summary = CompareSummary(
        total=cmp_breakdown.total,
        completed=cmp_breakdown.completed,
        processing=cmp_breakdown.processing,
        failed=cmp_breakdown.failed,
        pass_count=cmp_pass,
        warning_count=cmp_warn,
        fail_count=cmp_fail,
    )

    shared_total = (
        await db.execute(select(func.count(SharedTsnFile.id)))
    ).scalar_one() or 0
    latest_shared_at = (
        await db.execute(select(func.max(SharedTsnFile.created_at)))
    ).scalar_one()

    device_total = (
        await db.execute(select(func.count(Arinc429Device.id)))
    ).scalar_one() or 0

    recent_r = await db.execute(
        select(ParseTask).order_by(ParseTask.created_at.desc()).limit(5)
    )
    recent_tasks = [
        RecentParseTask(
            id=t.id,
            filename=t.filename,
            status=t.status or "",
            progress=int(t.progress or 0),
            parsed_packets=int(t.parsed_packets or 0),
            created_at=t.created_at,
            completed_at=t.completed_at,
        )
        for t in recent_r.scalars().all()
    ]

    today = datetime.utcnow().date()
    start_day = today - timedelta(days=6)
    trend_r = await db.execute(
        select(
            func.strftime("%Y-%m-%d", ParseTask.created_at).label("d"),
            func.count(ParseTask.id),
        )
        .where(ParseTask.created_at >= datetime.combine(start_day, datetime.min.time()))
        .group_by("d")
    )
    trend_map = {row[0]: int(row[1] or 0) for row in trend_r.all()}
    trend_series: List[DailyCount] = []
    for i in range(7):
        d = start_day + timedelta(days=i)
        key = d.isoformat()
        trend_series.append(DailyCount(date=key, count=trend_map.get(key, 0)))

    return OverviewResponse(
        generated_at=datetime.utcnow(),
        users={
            "total": int(users_total),
            "admin_total": int(admin_total),
        },
        parse_tasks=parse_breakdown,
        parse_results_total=int(parse_results_total),
        event_analysis=fm_summary,
        fcc_event_analysis=fcc_summary,
        auto_flight_analysis=auto_flight,
        compare_tasks=compare_summary,
        shared_tsn={
            "total": int(shared_total),
            "latest_at": latest_shared_at.isoformat() if latest_shared_at else None,
        },
        protocol_devices_total=int(device_total),
        recent_parse_tasks=recent_tasks,
        parse_tasks_trend_7d=trend_series,
    )
