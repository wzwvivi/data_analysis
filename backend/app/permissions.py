# -*- coding: utf-8 -*-
"""角色与权限定义"""
from dataclasses import dataclass


ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_DATA_MANAGER_TSN = "data_manager_tsn"
ROLE_DATA_MANAGER_FCC = "data_manager_fcc"
ROLE_DATA_MANAGER_GROUND = "data_manager_ground"
ROLE_LEADER = "leader"
ROLE_DEV_FCC = "dev_fcc"
ROLE_DEV_FMS = "dev_fms"
ROLE_DEV_AUTO_FLIGHT = "dev_auto_flight"
ROLE_DEVICE_TEAM = "device_team"
ROLE_NETWORK_TEAM = "network_team"

# 已下线角色（保留别名以兼容可能残留的历史 import；对应账号迁移到 network_team）
ROLE_DEV_TSN = ROLE_NETWORK_TEAM

ROLE_KEYS = [
    ROLE_ADMIN,
    ROLE_USER,  # 兼容历史账号，后续可迁移掉
    ROLE_DATA_MANAGER_TSN,
    ROLE_DATA_MANAGER_FCC,
    ROLE_DATA_MANAGER_GROUND,
    ROLE_LEADER,
    ROLE_DEV_FCC,
    ROLE_DEV_FMS,
    ROLE_DEV_AUTO_FLIGHT,
    ROLE_DEVICE_TEAM,
    ROLE_NETWORK_TEAM,
]

PAGE_DASHBOARD = "dashboard"
PAGE_UPLOAD = "upload"
PAGE_TASKS = "tasks"
PAGE_TASK_DETAIL = "tasks/:taskId"
PAGE_TASK_ANALYSIS = "tasks/:taskId/analysis"
PAGE_TASK_EVENT_ANALYSIS = "tasks/:taskId/event-analysis"
# 飞管事件分析（原 PAGE_EVENT_ANALYSIS，Phase 1 rename）
PAGE_FMS_EVENT_ANALYSIS = "fms-event-analysis"
PAGE_FMS_EVENT_ANALYSIS_TASK = "fms-event-analysis/task/:analysisTaskId"
# 向后兼容别名
PAGE_EVENT_ANALYSIS = PAGE_FMS_EVENT_ANALYSIS
PAGE_EVENT_ANALYSIS_TASK = PAGE_FMS_EVENT_ANALYSIS_TASK
PAGE_FCC_EVENT_ANALYSIS = "fcc-event-analysis"
PAGE_FCC_EVENT_ANALYSIS_TASK = "fcc-event-analysis/task/:analysisTaskId"
PAGE_AUTO_FLIGHT_ANALYSIS = "auto-flight-analysis"
PAGE_AUTO_FLIGHT_ANALYSIS_TASK = "auto-flight-analysis/task/:taskId"
PAGE_COMPARE = "compare"
PAGE_COMPARE_TASK = "compare/:taskId"
PAGE_NETWORK_CONFIG = "network-config"
PAGE_DEVICE_PROTOCOL = "device-protocol"
PAGE_ADMIN_PLATFORM_DATA = "admin/platform-data"
PAGE_ADMIN_CONFIGURATIONS = "admin/configurations"
PAGE_ADMIN_USERS = "admin/users"
PAGE_WORKBENCH = "workbench"
PAGE_WORKBENCH_DETAIL = "workbench/:sortieId"
# 飞行助手分析 (flight_data_webapp) 外链入口, 仅用于菜单可见性。
# 实际访问控制依赖网络层/反代, 因为它是独立 Flask 服务且自身无鉴权。
PAGE_FLIGHT_ASSISTANT = "flight-assistant"


@dataclass(frozen=True)
class RoleMeta:
    key: str
    name: str
    description: str


ROLE_META_LIST = [
    RoleMeta(ROLE_ADMIN, "管理员", "使用平台所有功能，包含用户管理与配置管理"),
    RoleMeta(ROLE_USER, "普通用户(兼容)", "历史兼容角色，建议迁移到更精细角色"),
    RoleMeta(ROLE_DATA_MANAGER_TSN, "数据管理(TSN记录器)", "上传TSN数据，管理相关解析任务"),
    RoleMeta(ROLE_DATA_MANAGER_FCC, "数据管理(飞控记录器)", "上传飞控记录数据，管理相关解析任务"),
    RoleMeta(ROLE_DATA_MANAGER_GROUND, "数据管理(地面网联)", "上传网联记录数据，管理相关解析任务"),
    RoleMeta(ROLE_LEADER, "领导/试飞团队", "查看试验架次总览和异常分析"),
    RoleMeta(ROLE_DEV_FCC, "开发团队(飞控)", "查看飞控事件分析内容"),
    RoleMeta(ROLE_DEV_FMS, "开发团队(飞管)", "查看飞管事件分析内容"),
    RoleMeta(ROLE_DEV_AUTO_FLIGHT, "开发团队(自动飞行)", "查看自动飞行分析内容"),
    RoleMeta(ROLE_DEVICE_TEAM, "设备团队", "查看设备事件分析与协议检查相关内容"),
    RoleMeta(ROLE_NETWORK_TEAM, "TSN/网络团队", "TSN 事件异常分析、TSN 网络配置管理、数据解析结果查看"),
]

ROLE_PAGE_ACCESS = {
    ROLE_ADMIN: ["*"],
    # 注：PAGE_DASHBOARD（仪表盘）仅 admin 可见；其它角色默认不含
    ROLE_USER: [PAGE_UPLOAD, PAGE_TASKS, PAGE_TASK_DETAIL, PAGE_TASK_ANALYSIS, PAGE_WORKBENCH, PAGE_WORKBENCH_DETAIL],
    ROLE_DATA_MANAGER_TSN: [PAGE_UPLOAD, PAGE_TASKS, PAGE_TASK_DETAIL, PAGE_TASK_ANALYSIS, PAGE_WORKBENCH, PAGE_WORKBENCH_DETAIL],
    ROLE_DATA_MANAGER_FCC: [PAGE_UPLOAD, PAGE_TASKS, PAGE_TASK_DETAIL, PAGE_TASK_ANALYSIS, PAGE_WORKBENCH, PAGE_WORKBENCH_DETAIL],
    ROLE_DATA_MANAGER_GROUND: [PAGE_UPLOAD, PAGE_TASKS, PAGE_TASK_DETAIL, PAGE_TASK_ANALYSIS, PAGE_WORKBENCH, PAGE_WORKBENCH_DETAIL],
    ROLE_LEADER: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_COMPARE,
        PAGE_COMPARE_TASK,
        PAGE_FMS_EVENT_ANALYSIS,
        PAGE_FMS_EVENT_ANALYSIS_TASK,
        PAGE_FCC_EVENT_ANALYSIS,
        PAGE_FCC_EVENT_ANALYSIS_TASK,
        PAGE_AUTO_FLIGHT_ANALYSIS,
        PAGE_AUTO_FLIGHT_ANALYSIS_TASK,
    ],
    ROLE_DEV_FCC: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_FCC_EVENT_ANALYSIS,
        PAGE_FCC_EVENT_ANALYSIS_TASK,
    ],
    ROLE_DEV_FMS: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_FMS_EVENT_ANALYSIS,
        PAGE_FMS_EVENT_ANALYSIS_TASK,
    ],
    ROLE_DEV_AUTO_FLIGHT: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_AUTO_FLIGHT_ANALYSIS,
        PAGE_AUTO_FLIGHT_ANALYSIS_TASK,
    ],
    ROLE_DEVICE_TEAM: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_FMS_EVENT_ANALYSIS,
        PAGE_FMS_EVENT_ANALYSIS_TASK,
        PAGE_DEVICE_PROTOCOL,
    ],
    ROLE_NETWORK_TEAM: [
        PAGE_UPLOAD,
        PAGE_TASKS,
        PAGE_TASK_DETAIL,
        PAGE_TASK_ANALYSIS,
        PAGE_WORKBENCH,
        PAGE_WORKBENCH_DETAIL,
        PAGE_FMS_EVENT_ANALYSIS,
        PAGE_FMS_EVENT_ANALYSIS_TASK,
        PAGE_NETWORK_CONFIG,
        PAGE_COMPARE,
        PAGE_COMPARE_TASK,
    ],
}

LEGACY_PAGE_KEY_ALIASES = {
    "event-analysis": PAGE_FMS_EVENT_ANALYSIS,
    "event-analysis/task/:analysisTaskId": PAGE_FMS_EVENT_ANALYSIS_TASK,
}


def is_valid_role(role: str) -> bool:
    return role in ROLE_KEYS


def get_role_pages(role: str) -> list[str]:
    return ROLE_PAGE_ACCESS.get(role, [])


def has_page_access(role: str, page_key: str) -> bool:
    normalized_page_key = LEGACY_PAGE_KEY_ALIASES.get(page_key, page_key)
    pages = get_role_pages(role)
    return "*" in pages or normalized_page_key in pages
