# -*- coding: utf-8 -*-
"""Phase 4 + fix：FccEventAnalysisService 端口分组策略。
策略：
  1. 细粒度 fcc_status / fcc_channel / fcc_fault 优先；
  2. 无细粒度 → 聚合 fcc_event ≥9 时按排序切片；
  3. 用户选了版本但无法满足 → strict 抛 BundleResolutionError；
  4. 未选版本 / 软 fallback → 回落默认。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pytest

from app.services.bundle.schema import Bundle, BundlePort
from app.services.event_rules.fcc_checksheet import (
    STATUS_PORTS as DEFAULT_STATUS,
    CHANNEL_PORTS as DEFAULT_CHANNEL,
    FAULT_PORTS as DEFAULT_FAULT,
)
from app.services.fcc_event_analysis_service import FccEventAnalysisService


def _make_bundle(
    role_to_ports: Dict[str, List[Tuple[int, Optional[str]]]],
) -> Bundle:
    """role_to_ports: {role: [(port, target_device), ...]}"""
    ports = {}
    role_ports: Dict[str, List[int]] = {}
    port_to_role: Dict[int, str] = {}
    for role, specs in role_to_ports.items():
        role_ports[role] = []
        for port, target in specs:
            ports[port] = BundlePort(
                port_number=port,
                port_role=role,
                target_device=target,
            )
            role_ports[role].append(port)
            port_to_role[port] = role
    return Bundle(
        protocol_version_id=7,
        protocol_version_name="v7",
        protocol_name="FCC-Test",
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        ports=ports,
        role_ports=role_ports,
        port_to_role=port_to_role,
    )


@pytest.mark.asyncio
async def test_fcc_port_groups_prefers_fine_grained_roles():
    svc = FccEventAnalysisService(db=None)
    bundle = _make_bundle({
        "fcc_status":  [(9001, "FCC1"), (9002, "FCC2"), (9003, "FCC3")],
        "fcc_channel": [(9011, "FCC1"), (9012, "FCC2"), (9013, "FCC3")],
        "fcc_fault":   [(9021, "FCC1"), (9022, "FCC2"), (9023, "FCC3")],
    })

    async def fake_load(_version_id, *, strict=False):
        return bundle

    svc._safe_load_bundle = fake_load  # type: ignore[assignment]

    status, channel, fault = await svc._resolve_fcc_port_groups(7)
    assert status == {9001: "FCC1", 9002: "FCC2", 9003: "FCC3"}
    assert channel == {9011: "FCC1", 9012: "FCC2", 9013: "FCC3"}
    assert fault == {9021: "FCC1", 9022: "FCC2", 9023: "FCC3"}


@pytest.mark.asyncio
async def test_fcc_port_groups_from_aggregate_role_splits_nine_ports():
    """未声明细粒度角色时，聚合 fcc_event 按排序切片作为兼容路径。"""
    svc = FccEventAnalysisService(db=None)
    bundle = _make_bundle({
        "fcc_event": [
            (9001, None), (9002, None), (9003, None),
            (9011, None), (9012, None), (9013, None),
            (9021, None), (9022, None), (9023, None),
        ],
    })

    async def fake_load(_version_id, *, strict=False):
        return bundle

    svc._safe_load_bundle = fake_load  # type: ignore[assignment]

    status, channel, fault = await svc._resolve_fcc_port_groups(7)
    assert status == {9001: "FCC1", 9002: "FCC2", 9003: "FCC3"}
    assert channel == {9011: "FCC1", 9012: "FCC2", 9013: "FCC3"}
    assert fault == {9021: "FCC1", 9022: "FCC2", 9023: "FCC3"}


@pytest.mark.asyncio
async def test_fcc_port_groups_strict_raises_when_role_incomplete():
    """用户显式选了版本，bundle 角色不足时应硬失败而非静默回落。"""
    svc = FccEventAnalysisService(db=None)
    bundle = _make_bundle({
        "fcc_event": [(9001, None), (9002, None), (9003, None)],  # 只有 3 个
    })

    async def fake_load(_version_id, *, strict=False):
        return bundle

    svc._safe_load_bundle = fake_load  # type: ignore[assignment]

    with pytest.raises(svc.BundleResolutionError):
        await svc._resolve_fcc_port_groups(7)


@pytest.mark.asyncio
async def test_fcc_port_groups_fallback_when_version_id_none():
    """未选版本 → 回落默认，不应抛错。"""
    svc = FccEventAnalysisService(db=None)

    async def fake_load(_version_id, *, strict=False):
        return None

    svc._safe_load_bundle = fake_load  # type: ignore[assignment]

    status, channel, fault = await svc._resolve_fcc_port_groups(None)
    assert status == dict(DEFAULT_STATUS)
    assert channel == dict(DEFAULT_CHANNEL)
    assert fault == dict(DEFAULT_FAULT)
