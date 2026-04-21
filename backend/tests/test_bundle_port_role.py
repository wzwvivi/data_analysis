# -*- coding: utf-8 -*-
"""Phase 2/4 覆盖：Bundle 里 port_role / role_ports / port_to_role 的
schema 往返以及 ports_for_role 查询辅助。
"""
from __future__ import annotations

from datetime import datetime

from app.services.bundle.schema import (
    Bundle,
    BundlePort,
    bundle_from_dict,
    bundle_to_dict,
)


def _build_sample_bundle() -> Bundle:
    now = datetime(2026, 4, 20, 12, 0, 0)
    ports = {
        9001: BundlePort(port_number=9001, port_role="fcc_event", message_name="FCC1_STATUS"),
        9002: BundlePort(port_number=9002, port_role="fcc_event", message_name="FCC2_STATUS"),
        9031: BundlePort(port_number=9031, port_role="auto_flight", target_device="FCC1"),
        9032: BundlePort(port_number=9032, port_role="auto_flight", target_device="FCC2"),
        7001: BundlePort(port_number=7001, port_role="tsn_anomaly"),
    }
    role_ports = {
        "fcc_event": [9001, 9002],
        "auto_flight": [9031, 9032],
        "tsn_anomaly": [7001],
    }
    port_to_role = {p: ports[p].port_role for p in ports}
    return Bundle(
        protocol_version_id=42,
        protocol_version_name="v42",
        protocol_name="Test",
        generated_at=now,
        ports=ports,
        role_ports=role_ports,
        port_to_role=port_to_role,
    )


def test_ports_for_role_returns_sorted_int_list():
    b = _build_sample_bundle()
    assert b.ports_for_role("auto_flight") == [9031, 9032]
    assert b.ports_for_role("fcc_event") == [9001, 9002]
    assert b.ports_for_role("unknown") == []


def test_bundle_roundtrip_preserves_port_role():
    b = _build_sample_bundle()
    data = bundle_to_dict(b)
    # 序列化后 ports / port_to_role 的 key 必须是 str（JSON 规范）
    assert all(isinstance(k, str) for k in data["ports"].keys())
    assert all(isinstance(k, str) for k in data["port_to_role"].keys())

    b2 = bundle_from_dict(data)
    # 反序列化后 key 应恢复为 int
    assert set(b2.ports.keys()) == {9001, 9002, 9031, 9032, 7001}
    assert b2.port_to_role[9031] == "auto_flight"
    assert b2.ports[9031].port_role == "auto_flight"
    assert b2.ports_for_role("auto_flight") == [9031, 9032]


def test_ports_for_role_tolerates_missing_role_ports():
    b = Bundle(protocol_version_id=1, generated_at=datetime.utcnow())
    assert b.ports_for_role("auto_flight") == []
