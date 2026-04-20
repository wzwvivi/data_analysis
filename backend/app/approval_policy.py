# -*- coding: utf-8 -*-
"""协议草稿审批链配置

历史：仅支持 TSN 网络配置默认审批链（``DEFAULT_APPROVAL_CHAIN``）。
扩展：按 draft_kind 选链，通过 ``CHAINS_BY_KIND`` 配置。
未显式配置的 kind 回退到 ``DEFAULT_APPROVAL_CHAIN``。
"""
from typing import List, Optional

from .permissions import (
    ROLE_ADMIN,
    ROLE_DEVICE_TEAM,
    ROLE_DEV_TSN,
    ROLE_NETWORK_TEAM,
)


# draft_kind 常量（和 models/device_protocol.py 保持一致，这里直接用字符串避免循环导入）
DRAFT_KIND_TSN_NETWORK = "tsn_network"
DRAFT_KIND_DEVICE_ARINC429 = "device_arinc429"
DRAFT_KIND_DEVICE_CAN = "device_can"
DRAFT_KIND_DEVICE_RS422 = "device_rs422"


# TSN 网络配置审批链：network_team 提 → device_team 会签 → dev_tsn 会签 → admin 终审
DEFAULT_APPROVAL_CHAIN: List[str] = [
    ROLE_NETWORK_TEAM,
    ROLE_DEVICE_TEAM,
    ROLE_DEV_TSN,
    ROLE_ADMIN,
]


# 设备协议（ARINC429 / CAN / RS422）审批链：
#   device_team 提（最懂设备协议）→ network_team 会签（关注端口/族影响）→ dev_tsn 会签（关注解析代码）→ admin 终审
DEVICE_APPROVAL_CHAIN: List[str] = [
    ROLE_DEVICE_TEAM,
    ROLE_NETWORK_TEAM,
    ROLE_DEV_TSN,
    ROLE_ADMIN,
]


CHAINS_BY_KIND: dict[str, List[str]] = {
    DRAFT_KIND_TSN_NETWORK: DEFAULT_APPROVAL_CHAIN,
    DRAFT_KIND_DEVICE_ARINC429: DEVICE_APPROVAL_CHAIN,
    DRAFT_KIND_DEVICE_CAN: DEVICE_APPROVAL_CHAIN,
    DRAFT_KIND_DEVICE_RS422: DEVICE_APPROVAL_CHAIN,
}


STEP_LABELS = {
    ROLE_NETWORK_TEAM: "网络团队",
    ROLE_DEVICE_TEAM: "设备团队",
    ROLE_DEV_TSN: "TSN 开发团队",
    ROLE_ADMIN: "管理员终审",
}


def get_chain_for_kind(kind: Optional[str]) -> List[str]:
    """按 draft_kind 获取审批链；未知 kind 回退到 TSN 默认链以向后兼容"""
    if not kind:
        return DEFAULT_APPROVAL_CHAIN
    return CHAINS_BY_KIND.get(kind, DEFAULT_APPROVAL_CHAIN)


def get_role_for_step(step_index: int, kind: Optional[str] = None) -> Optional[str]:
    chain = get_chain_for_kind(kind)
    if 0 <= step_index < len(chain):
        return chain[step_index]
    return None


def role_can_sign_off(user_role: str, step_role: str) -> bool:
    """admin 作为兜底可以代表任何 step 进行会签（但具体流程里不鼓励）"""
    if user_role == ROLE_ADMIN:
        return True
    return user_role == step_role
