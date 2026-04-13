# -*- coding: utf-8 -*-
"""统一重任务调度器：使用进程池隔离 CPU/IO 重任务。"""

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Callable, Any


_DEFAULT_CPU_CORES = int(os.environ.get("SERVER_CPU_CORES", "4"))
# 默认 CPU_CORES // 2；也可通过 TASK_PROCESS_WORKERS 覆盖。
_DEFAULT_TASK_WORKERS = max(1, _DEFAULT_CPU_CORES // 2)
_TASK_WORKERS = int(os.environ.get("TASK_PROCESS_WORKERS", str(_DEFAULT_TASK_WORKERS)))

_POOL = ProcessPoolExecutor(max_workers=max(1, _TASK_WORKERS))


async def submit_process_job(job: Callable[..., Any], *args: Any) -> None:
    """把重任务提交到独立子进程池，不阻塞 API 事件循环。"""
    loop = asyncio.get_running_loop()
    fn = partial(job, *args)
    await loop.run_in_executor(_POOL, fn)

