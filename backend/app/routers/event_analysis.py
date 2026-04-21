# -*- coding: utf-8 -*-
"""Phase 1 向后兼容 shim 路由。

原 prefix `/api/event-analysis` 的全部路由已搬迁到 :mod:`.fms_event_analysis`
（新 prefix `/api/fms-event-analysis`）。为了让历史前端/脚本不立即断裂，这里
把完全一样的 handler 函数挂在旧 prefix 下再注册一份，下一个版本移除。
"""
from fastapi import APIRouter, Depends

from ..deps import get_current_user
from . import fms_event_analysis as _fms

# 复用 fms_event_analysis 的所有路由函数，但换 prefix 和 tags，单独创建一个 router。
router = APIRouter(
    prefix="/api/event-analysis",
    tags=["事件分析(兼容)"],
    dependencies=[Depends(get_current_user)],
)

# 把 fms_event_analysis.router 的所有 routes 克隆进来（保留原 endpoint 函数）
for _route in _fms.router.routes:
    # 去掉新 prefix，再加上旧 prefix
    _new_path = _route.path.replace("/api/fms-event-analysis", "", 1)
    router.add_api_route(
        _new_path,
        _route.endpoint,
        methods=list(_route.methods) if _route.methods else None,
        response_model=getattr(_route, "response_model", None),
        name=f"legacy_{_route.name}" if _route.name else None,
        include_in_schema=False,
    )
