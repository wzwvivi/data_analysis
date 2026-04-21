# -*- coding: utf-8 -*-
"""Phase 3 覆盖：payload_layouts 常量表的基本健全性（非 ICD 部分保持写死，
但至少保证偏移量没越界 / 类型合法）。
"""
from __future__ import annotations

from app.services import payload_layouts as pl


def test_tsn_header_and_frame_constants_present():
    assert pl.TSN_HEADER_LEN > 0
    assert pl.AUTO_FLIGHT_FRAME_SIZE > 0


def test_fcc_offsets_are_nonnegative_ints():
    for name in (
        "FCC_STATUS_VOTE_OFFSET",
        "FCC_CHANNEL_IRS_SEL_OFFSET",
        "FCC_CHANNEL_RA_SEL_OFFSET",
        "FCC_FAULT_IRS_BITMAP_OFFSET",
        "FCC_FAULT_RA_BITMAP_OFFSET",
    ):
        val = getattr(pl, name)
        assert isinstance(val, int), f"{name} 必须是 int"
        assert val >= 0, f"{name} 必须是非负数"


def test_auto_flight_layout_fits_within_frame():
    for name, spec in pl.AUTO_FLIGHT_LAYOUT.items():
        assert len(spec) == 2, f"{name} 的布局应为 (offset, type)"
        off, typ = spec
        assert isinstance(off, int) and off >= 0
        assert typ in {"u8", "f32"}, f"{name} 类型非法: {typ}"
        size = 1 if typ == "u8" else 4
        assert off + size <= pl.AUTO_FLIGHT_FRAME_SIZE, (
            f"{name} 越过自动飞行帧长 {pl.AUTO_FLIGHT_FRAME_SIZE}: offset={off}"
        )


def test_auto_flight_layout_has_required_fields_for_analyzer():
    """AutoFlightAnalyzer 至少要能拿到这些字段做触底/稳态判断。"""
    required = {
        "ap_engaged", "at_engaged", "air_ground",
        "lon_mode_active", "af_warning",
        "lat_track_error_m", "vert_track_error_m",
        "speed_cmd_mps", "current_airspeed_mps",
    }
    missing = required - set(pl.AUTO_FLIGHT_LAYOUT.keys())
    assert not missing, f"AUTO_FLIGHT_LAYOUT 缺字段: {missing}"
