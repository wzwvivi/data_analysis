# -*- coding: utf-8 -*-
from .protocol import router as protocol_router
from .parse import router as parse_router
from .event_analysis import router as event_analysis_router
from .compare import router as compare_router
from .auth import router as auth_router
from .shared_tsn import router as shared_tsn_router

__all__ = [
    "protocol_router",
    "parse_router",
    "event_analysis_router",
    "compare_router",
    "auth_router",
    "shared_tsn_router",
]
