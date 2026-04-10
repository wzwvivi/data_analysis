# -*- coding: utf-8 -*-
"""CPU/IO 重任务：在独立子进程中执行，避免阻塞 API 进程。"""

import asyncio
import traceback


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


def run_event_analysis_task_job(parse_task_id: int, rule_template: str) -> None:
    """解析任务关联的事件分析子进程入口。"""
    print(
        f"[事件分析/子进程] 开始执行 parse_task_id={parse_task_id}, rule={rule_template}"
    )
    try:
        from .database import async_session
        from .services import EventAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = EventAnalysisService(db)
                ok = await service.run_analysis(parse_task_id, rule_template)
                print(
                    f"[事件分析/子进程] 完成 parse_task_id={parse_task_id}, result={ok}"
                )

        asyncio.run(_run())
    except Exception as exc:
        print(f"[事件分析/子进程] 失败 parse_task_id={parse_task_id}: {exc}")
        traceback.print_exc()


def run_standalone_event_analysis_task_job(analysis_task_id: int) -> None:
    """独立事件分析子进程入口。"""
    print(f"[独立事件分析/子进程] 开始执行 analysis_task_id={analysis_task_id}")
    try:
        from .database import async_session
        from .services import EventAnalysisService

        async def _run() -> None:
            async with async_session() as db:
                service = EventAnalysisService(db)
                ok = await service.run_standalone_analysis(analysis_task_id)
                print(
                    f"[独立事件分析/子进程] 完成 analysis_task_id={analysis_task_id}, result={ok}"
                )

        asyncio.run(_run())
    except Exception as exc:
        print(f"[独立事件分析/子进程] 失败 analysis_task_id={analysis_task_id}: {exc}")
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
