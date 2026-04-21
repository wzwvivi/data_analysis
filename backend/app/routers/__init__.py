# -*- coding: utf-8 -*-
from .protocol import router as protocol_router
from .parse import router as parse_router
from .fms_event_analysis import router as fms_event_analysis_router
from .event_analysis import router as event_analysis_router  # Phase 1 back-compat
from .fcc_event_analysis import router as fcc_event_analysis_router
from .auto_flight_analysis import router as auto_flight_analysis_router
from .compare import router as compare_router
from .auth import router as auth_router
from .shared_tsn import router as shared_tsn_router
from .arinc429 import router as arinc429_router
from .role_config import router as role_config_router
from .network_config import router as network_config_router
from .device_protocol import router as device_protocol_router
from .notifications import router as notifications_router
from .dashboard import router as dashboard_router
from .workbench import router as workbench_router

__all__ = [
    "protocol_router",
    "parse_router",
    "fms_event_analysis_router",
    "event_analysis_router",
    "fcc_event_analysis_router",
    "auto_flight_analysis_router",
    "compare_router",
    "auth_router",
    "shared_tsn_router",
    "arinc429_router",
    "role_config_router",
    "network_config_router",
    "device_protocol_router",
    "notifications_router",
    "dashboard_router",
    "workbench_router",
]
