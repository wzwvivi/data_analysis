# -*- coding: utf-8 -*-
"""统一重任务调度器：使用进程池隔离 CPU/IO 重任务。

额外支持：
- 解析任务注册到 `_PARSE_FUTURES`，便于 API 层请求"软取消"——在 DB 里
  标记 `cancel_requested=1`，子进程轮询到后主动退出并把任务置为 cancelled。
- 如果协作取消无法落地（例如 future 已经在 run_in_executor 层阻塞），API 还可以选择
  `future.cancel()`，让尚未开始的任务直接作废。
"""

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any, Callable, Dict, Optional


_DEFAULT_CPU_CORES = int(os.environ.get("SERVER_CPU_CORES", "4"))
# 默认 CPU_CORES // 2；也可通过 TASK_PROCESS_WORKERS 覆盖。
_DEFAULT_TASK_WORKERS = max(1, _DEFAULT_CPU_CORES // 2)
_TASK_WORKERS = int(os.environ.get("TASK_PROCESS_WORKERS", str(_DEFAULT_TASK_WORKERS)))

_POOL = ProcessPoolExecutor(max_workers=max(1, _TASK_WORKERS))

# 当前挂起 / 运行中的解析任务 future。key=task_id
_PARSE_FUTURES: Dict[int, "asyncio.Future[Any]"] = {}


async def submit_process_job(job: Callable[..., Any], *args: Any) -> None:
    """把重任务提交到独立子进程池，不阻塞 API 事件循环。"""
    loop = asyncio.get_running_loop()
    fn = partial(job, *args)
    await loop.run_in_executor(_POOL, fn)


async def submit_parse_job(job: Callable[..., Any], task_id: int, *args: Any) -> None:
    """专用于解析任务的提交入口，会把 future 注册起来以便后续取消。"""
    loop = asyncio.get_running_loop()
    fn = partial(job, task_id, *args)
    future = loop.run_in_executor(_POOL, fn)
    _PARSE_FUTURES[task_id] = future
    try:
        await future
    finally:
        _PARSE_FUTURES.pop(task_id, None)


def cancel_parse_future(task_id: int) -> bool:
    """尝试在运行中/排队中的 future 层面直接取消。

    仅在 future 尚未开始执行时能真正生效；已运行的任务需依赖 DB 软取消标志。
    """
    fut: Optional["asyncio.Future[Any]"] = _PARSE_FUTURES.get(task_id)
    if fut is None:
        return False
    try:
        return bool(fut.cancel())
    except Exception:
        return False
