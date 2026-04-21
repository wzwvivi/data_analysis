# -*- coding: utf-8 -*-
"""CPU/IO 重任务：在独立子进程中执行，避免阻塞 API 进程。"""

import asyncio
import traceback
from typing import Optional


def run_parse_task_job(task_id: int) -> None:
    """解析任务子进程入口。"""
    print(f"[解析任务/子进程] 开始执行 task_id={task_id}")
    try:
        from .database import async_session
        from .services import ParserService

        async def _run() -> None:
            async with async_session() as db:
                service = ParserService(db)
                ok = await service.parse_pcapng(task_id)
                print(f"[解析任务/子进程] 完成 task_id={task_id}, result={ok}")

        asyncio.run(_run())
    except Exception as exc:
        print(f"[解析任务/子进程] 失败 task_id={task_id}: {exc}")
        traceback.print_exc()


def run_fms_event_analysis_task_job(
    parse_task_id: int,
    rule_template: str,
    bundle_version_id: Optional[int] = None,
) -> None:
    """解析任务关联的飞管事件分析子进程入口。

    bundle_version_id 可选（MR4）；为 None 时由 service 根据 ParseTask 推断。
    """
    print(
        f"[飞管事件分析/子进程] 开始执行 parse_task_id={parse_task_id}, "
        f"rule={rule_template}, bundle_version_id={bundle_version_id}"
    )
    try:
        from .database import async_session
        from .services import FmsEventAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = FmsEventAnalysisService(db)
                ok = await service.run_analysis(
                    parse_task_id,
                    rule_template,
                    bundle_version_id=bundle_version_id,
                )
                print(
                    f"[飞管事件分析/子进程] 完成 parse_task_id={parse_task_id}, result={ok}"
                )

        asyncio.run(_run())
    except Exception as exc:
        print(f"[飞管事件分析/子进程] 失败 parse_task_id={parse_task_id}: {exc}")
        traceback.print_exc()


# Phase 1 back-compat aliases (旧子进程入口名；等没人用了可删除)
run_event_analysis_task_job = run_fms_event_analysis_task_job


def run_standalone_fms_event_analysis_task_job(analysis_task_id: int) -> None:
    """独立飞管事件分析子进程入口。"""
    print(f"[独立飞管事件分析/子进程] 开始执行 analysis_task_id={analysis_task_id}")
    try:
        from .database import async_session
        from .services import FmsEventAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = FmsEventAnalysisService(db)
                ok = await service.run_standalone_analysis(analysis_task_id)
                print(
                    f"[独立飞管事件分析/子进程] 完成 analysis_task_id={analysis_task_id}, result={ok}"
                )

        asyncio.run(_run())
    except Exception as exc:
        print(f"[独立飞管事件分析/子进程] 失败 analysis_task_id={analysis_task_id}: {exc}")
        traceback.print_exc()


# Phase 1 back-compat alias
run_standalone_event_analysis_task_job = run_standalone_fms_event_analysis_task_job


def run_fcc_event_analysis_task_job(
    analysis_task_id: int,
    divergence_tolerance_ms: int = 100,
) -> None:
    """飞控事件分析子进程入口。"""
    print(
        "[飞控事件分析/子进程] 开始执行 "
        f"analysis_task_id={analysis_task_id}, "
        f"divergence_tolerance_ms={divergence_tolerance_ms}"
    )
    try:
        from .database import async_session
        from .services import FccEventAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = FccEventAnalysisService(db)
                ok = await service.run_standalone_analysis(
                    analysis_task_id,
                    divergence_tolerance_ms=divergence_tolerance_ms,
                )
                print(
                    f"[飞控事件分析/子进程] 完成 analysis_task_id={analysis_task_id}, result={ok}"
                )

        asyncio.run(_run())
    except Exception as exc:
        print(f"[飞控事件分析/子进程] 失败 analysis_task_id={analysis_task_id}: {exc}")
        traceback.print_exc()


def run_compare_task_job(task_id: int) -> None:
    """双交换机比对子进程入口。"""
    print(f"[比对任务/子进程] 开始执行 task_id={task_id}")
    try:
        from .database import async_session
        from .services import CompareService

        async def _run() -> None:
            async with async_session() as db:
                service = CompareService(db)
                ok = await service.run_compare(task_id)
                print(f"[比对任务/子进程] 完成 task_id={task_id}, result={ok}")

        asyncio.run(_run())
    except Exception as exc:
        print(f"[比对任务/子进程] 失败 task_id={task_id}: {exc}")
        traceback.print_exc()


def run_auto_flight_analysis_task_job(task_id: int) -> None:
    """自动飞行性能分析子进程入口。"""
    print(f"[自动飞行性能分析/子进程] 开始执行 task_id={task_id}")
    try:
        from .database import async_session
        from .services import AutoFlightAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = AutoFlightAnalysisService(db)
                ok = await service.run_analysis(task_id)
                print(f"[自动飞行性能分析/子进程] 完成 task_id={task_id}, result={ok}")

        asyncio.run(_run())
    except Exception as exc:
        print(f"[自动飞行性能分析/子进程] 失败 task_id={task_id}: {exc}")
        traceback.print_exc()
