# -*- coding: utf-8 -*-
"""
自动飞行数据解析器（飞控发出数据-TSN版-V13.4）

端口：
  FCC1:9031, FCC2:9032, FCC3:9033, BCM:9034

帧结构：
  - TSN头 8B：协议填充(4) + 功能状态集(4)
  - 结构体 124B
"""
from __future__ import annotations

import struct
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout
# 设备协议 payload 内部字段布局（非 ICD 数据）统一在 payload_layouts 声明。
from ..payload_layouts import (
    TSN_HEADER_LEN,
    AUTO_FLIGHT_FRAME_SIZE as FRAME_SIZE,
    AUTO_FLIGHT_LAYOUT,
)


AUTO_FLIGHT_PORTS = {9031: "FCC1", 9032: "FCC2", 9033: "FCC3", 9034: "BCM"}


def _u8(data: bytes, offset0: int) -> int:
    return int(data[offset0])


def _f32(data: bytes, offset0: int) -> float:
    return float(struct.unpack_from("<f", data, offset0)[0])


def _decode_auto_flight_frame(data: bytes) -> Dict[str, Any]:
    """按 AUTO_FLIGHT_LAYOUT 解码。返回 {field_name: value}。"""
    out: Dict[str, Any] = {}
    for name, (off, typ) in AUTO_FLIGHT_LAYOUT.items():
        if typ == "u8":
            if off >= len(data):
                continue
            out[name] = _u8(data, off)
        elif typ == "f32":
            if off + 4 > len(data):
                continue
            out[name] = _f32(data, off)
    return out


@ParserRegistry.register
class AutoFlightParser(BaseParser):
    parser_key = "auto_flight_v13"
    name = "自动飞行数据"
    supported_ports: List[int] = []

    OUTPUT_COLUMNS = [
        "timestamp",
        "source_port",
        "source_fcc",
        "raw_data",
        "packet_size",
        "ap_engaged",
        "at_engaged",
        "air_ground",
        "flight_phase",
        "auto_mode",
        "current_leg",
        "lat_mode_armed",
        "lat_mode_active",
        "lon_mode_armed",
        "lon_mode_active",
        "thr_mode_armed",
        "thr_mode_active",
        "af_warning",
        "lat_track_error_m",
        "vert_track_error_m",
        "speed_cmd_mps",
        "altitude_cmd_m",
        "vs_cmd_mps",
        "roll_cmd_deg",
        "pitch_cmd_deg",
        "target_heading_deg",
        "target_thrust_n",
        "target_rotor_rpm",
        "current_altitude_m",
        "current_airspeed_mps",
        "current_airspeed_acc_mps2",
        "current_groundspeed_mps",
        "current_calibrated_airspeed_mps",
        "current_calibrated_airspeed_acc_mps2",
        "height_source",
        "airspeed_source",
        "ap_active",
        "at_active",
        "alt_active",
        "vs_active",
        "mission_active",
        "land_active",
    ]

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not payload:
            return None

        out: Dict[str, Any] = {
            "timestamp": timestamp,
            "source_port": port,
            "source_fcc": AUTO_FLIGHT_PORTS.get(port),
            "raw_data": payload.hex(),
            "packet_size": len(payload),
        }

        if port not in AUTO_FLIGHT_PORTS:
            return out
        if len(payload) < TSN_HEADER_LEN + FRAME_SIZE:
            return out

        data = payload[TSN_HEADER_LEN:TSN_HEADER_LEN + FRAME_SIZE]
        try:
            out.update(_decode_auto_flight_frame(data))
        except Exception:
            return out

        return out

    def get_output_columns(self, port: int) -> List[str]:
        return self.OUTPUT_COLUMNS
