# -*- coding: utf-8 -*-
"""Phase 4 + fix：AutoFlightAnalysisService 按 bundle.port_role 解析
auto_flight / irs_input 两组端口；bundle 缺失时 strict 抛错 / 非 strict 回落默认。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.auto_flight_analysis_service import (
    AutoFlightAnalysisService,
    BundleResolutionError,
    DEFAULT_AUTO_FLIGHT_PORTS,
    IRS_PORT_HINTS,
)
from app.services.bundle.schema import Bundle, BundlePort


def _build_bundle(auto_specs, irs_specs=()):
    """auto_specs/irs_specs: list of (port, primary_device, message_name)."""
    ports = {}
    role_ports = {}
    port_to_role = {}
    for role, specs, dev_attr in (
        ("auto_flight", auto_specs, "target_device"),
        ("irs_input", irs_specs, "source_device"),
    ):
        role_list = []
        for p, dev, msg in specs:
            ports[p] = BundlePort(
                port_number=p,
                port_role=role,
                message_name=msg,
                **{dev_attr: dev},
            )
            role_list.append(p)
            port_to_role[p] = role
        if role_list:
            role_ports[role] = role_list
    return Bundle(
        protocol_version_id=11,
        protocol_version_name="v11",
        protocol_name="AF-Test",
        generated_at=datetime(2026, 4, 20, 12, 0, 0),
        ports=ports,
        role_ports=role_ports,
        port_to_role=port_to_role,
    )


@pytest.mark.asyncio
async def test_port_mapping_prefers_bundle_target_device(monkeypatch):
    svc = AutoFlightAnalysisService(db=None)
    bundle = _build_bundle([
        (9031, "FCC1", "AUTO_FLIGHT_FCC1"),
        (9032, "FCC2", "AUTO_FLIGHT_FCC2"),
        (9033, "FCC3", "AUTO_FLIGHT_FCC3"),
    ])

    import app.services.auto_flight_analysis_service as af_mod

    async def fake_load(_db, _vid, *, strict=False):
        return bundle

    monkeypatch.setattr(af_mod, "_safe_load_bundle", fake_load)

    auto_map, irs_map = await svc._resolve_port_mapping(11)
    assert auto_map == {9031: "FCC1", 9032: "FCC2", 9033: "FCC3"}
    # 未在 bundle 里声明 irs_input → 回落默认
    assert irs_map == dict(IRS_PORT_HINTS)


@pytest.mark.asyncio
async def test_port_mapping_strict_raises_when_bundle_load_fails(monkeypatch):
    svc = AutoFlightAnalysisService(db=None)
    import app.services.auto_flight_analysis_service as af_mod

    async def fake_load(_db, _vid, *, strict=False):
        if strict:
            raise BundleResolutionError("bundle load failed")
        return None

    monkeypatch.setattr(af_mod, "_safe_load_bundle", fake_load)

    with pytest.raises(BundleResolutionError):
        await svc._resolve_port_mapping(99)


@pytest.mark.asyncio
async def test_port_mapping_falls_back_when_version_id_none():
    svc = AutoFlightAnalysisService(db=None)
    auto_map, irs_map = await svc._resolve_port_mapping(None)
    assert auto_map == dict(DEFAULT_AUTO_FLIGHT_PORTS)
    assert irs_map == dict(IRS_PORT_HINTS)


@pytest.mark.asyncio
async def test_port_mapping_resolves_irs_from_bundle(monkeypatch):
    svc = AutoFlightAnalysisService(db=None)
    bundle = _build_bundle(
        [(9031, "FCC1", "AUTO_FCC1")],
        irs_specs=[
            (1001, "IRS1", "IRS1_ATT"),
            (1002, "IRS2", "IRS2_ATT"),
            (1003, "IRS3", "IRS3_ATT"),
        ],
    )

    import app.services.auto_flight_analysis_service as af_mod

    async def fake_load(_db, _vid, *, strict=False):
        return bundle

    monkeypatch.setattr(af_mod, "_safe_load_bundle", fake_load)

    _, irs_map = await svc._resolve_port_mapping(11)
    assert irs_map == {1001: "IRS1", 1002: "IRS2", 1003: "IRS3"}


@pytest.mark.asyncio
async def test_port_mapping_infers_label_from_message_name(monkeypatch):
    svc = AutoFlightAnalysisService(db=None)
    bundle = _build_bundle([
        (9031, None, "AUTO_FCC1"),
        (9032, "", "AUTO_FCC2"),
        (9034, None, "BCM_DATA"),
    ])

    import app.services.auto_flight_analysis_service as af_mod

    async def fake_load(_db, _vid, *, strict=False):
        return bundle

    monkeypatch.setattr(af_mod, "_safe_load_bundle", fake_load)

    auto_map, _ = await svc._resolve_port_mapping(11)
    assert auto_map[9031] == "FCC1"
    assert auto_map[9032] == "FCC2"
    assert auto_map[9034] == "BCM"
