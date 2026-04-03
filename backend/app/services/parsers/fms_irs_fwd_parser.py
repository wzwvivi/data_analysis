# -*- coding: utf-8 -*-
"""
飞管给惯导转发数据及初始化数据解析器 (V0.4)

根据《飞管给惯导转发数据及初始化数据协议V0.4-nh20260403》实现。
FMS1/FMS2 通过 TSN 向 IRS1/2/3 发送转发数据及手动对准指令。

TSN 包结构：协议填充(4B) + 功能状态集(4B) + 消息体(39B)
消息体小端序，帧头 0xEB 0x90。

端口：
  FMS1→IRS1: 8025  FMS1→IRS2: 8026  FMS1→IRS3: 8027
  FMS2→IRS1: 8039  FMS2→IRS2: 8040  FMS2→IRS3: 8041
"""
import struct
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout

TSN_HEADER_LEN = 8
FRAME_LEN = 39
HEADER_MAGIC = b"\xEB\x90"

_PORT_FMS = {
    8025: ("FMS1", "IRS1"), 8026: ("FMS1", "IRS2"), 8027: ("FMS1", "IRS3"),
    8039: ("FMS2", "IRS1"), 8040: ("FMS2", "IRS2"), 8041: ("FMS2", "IRS3"),
}

_ALIGN_CMD = {0: "无指令", 1: "手动对准"}

_ALL_PORTS = sorted(_PORT_FMS.keys())

_COMMON_COLS = [
    "timestamp", "source_port", "fms_id", "target_irs",
    "packet_size", "header_ok", "checksum_ok",
]

_SIGNAL_COLS = [
    "data_length",
    "align_cmd", "align_cmd_cn",
    "manual_longitude_deg", "manual_latitude_deg", "manual_altitude_m",
    "atm_baro_altitude_ft", "atm_indicated_airspeed_kn",
    "atm_true_airspeed_kn", "atm_static_pressure_hpa",
    "atm_dynamic_pressure_hpa",
    "validity_baro_alt", "validity_ias", "validity_tas",
    "validity_static_p", "validity_dynamic_p",
    "validity_raw",
    "checksum_raw",
]

OUTPUT_COLUMNS = _COMMON_COLS + _SIGNAL_COLS


def _verify_checksum(data: bytes) -> bool:
    """和校验：Byte3-Byte37 累加和 == Byte38-39 (uint16 LE)"""
    if len(data) < FRAME_LEN:
        return False
    body_sum = sum(data[2:37]) & 0xFFFF
    expected = struct.unpack_from("<H", data, 37)[0]
    return body_sum == expected


@ParserRegistry.register
class FMSIRSForwardParser(BaseParser):
    parser_key = "fms_irs_fwd_v0.4"
    name = "飞管给惯导转发数据"
    supported_ports: List[int] = _ALL_PORTS

    OUTPUT_COLUMNS = OUTPUT_COLUMNS

    def can_parse_port(self, port: int) -> bool:
        return port in _PORT_FMS

    def get_output_columns(self, port: int) -> List[str]:
        return OUTPUT_COLUMNS

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not payload or len(payload) < TSN_HEADER_LEN + 2:
            return None

        fms_irs = _PORT_FMS.get(port)
        if not fms_irs:
            return None

        fms_id, target_irs = fms_irs
        data = payload[TSN_HEADER_LEN:]

        out: Dict[str, Any] = {
            "timestamp": timestamp,
            "source_port": port,
            "fms_id": fms_id,
            "target_irs": target_irs,
            "packet_size": len(payload),
            "header_ok": False,
            "checksum_ok": False,
        }

        if len(data) < FRAME_LEN:
            return out

        if data[0:2] != HEADER_MAGIC:
            return out
        out["header_ok"] = True

        out["checksum_ok"] = _verify_checksum(data)
        out["data_length"] = data[2]

        cmd = data[3]
        out["align_cmd"] = cmd
        out["align_cmd_cn"] = _ALIGN_CMD.get(cmd, f"未知({cmd})")

        out["manual_longitude_deg"] = struct.unpack_from("<i", data, 4)[0] * 1e-7
        out["manual_latitude_deg"] = struct.unpack_from("<i", data, 8)[0] * 1e-7
        out["manual_altitude_m"] = struct.unpack_from("<i", data, 12)[0] * 0.01

        out["atm_baro_altitude_ft"] = struct.unpack_from("<i", data, 16)[0] * 0.25
        out["atm_indicated_airspeed_kn"] = struct.unpack_from("<I", data, 20)[0] * 0.125
        out["atm_true_airspeed_kn"] = struct.unpack_from("<I", data, 24)[0] * 0.125
        out["atm_static_pressure_hpa"] = struct.unpack_from("<I", data, 28)[0] * 0.03125
        out["atm_dynamic_pressure_hpa"] = struct.unpack_from("<i", data, 32)[0] * 0.03125

        validity = data[36]
        out["validity_raw"] = validity
        out["validity_baro_alt"] = (validity >> 0) & 1
        out["validity_ias"] = (validity >> 1) & 1
        out["validity_tas"] = (validity >> 2) & 1
        out["validity_static_p"] = (validity >> 3) & 1
        out["validity_dynamic_p"] = (validity >> 4) & 1

        out["checksum_raw"] = struct.unpack_from("<H", data, 37)[0]

        return out
