# -*- coding: utf-8 -*-
"""
270V&28V 动力电池 BMS CAN 解析器 (V2.5.2)

TSN 包结构:
  Byte 0-3 : 协议填充 (4B)
  Byte 4-7 : 功能状态集 (4B)
  Byte 8+  : CAN_FRAME 序列, 每帧 16B, 每 4 帧后插入 4B 功能状态集

CAN_FRAME (16B) = 4B CAN-ID (big-endian) + 4B DLC/状态 + 8B 数据

信号: Motorola byte-order, Unsigned, 物理值 = raw * factor + offset
输出: 通用列名 + pack_id 区分电池包 (P28/PE/PL/PR/FMC1/FMC2)
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseParser, ParserRegistry, FieldLayout
from .bms800v_parser import _extract_motorola, _can_frame_valid

_DATA_DIR = Path(__file__).parent


def _load_data() -> dict:
    p = _DATA_DIR / "bms270v_data.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


_DATA: dict = _load_data()

_PORT_MAP: Dict[int, List[Tuple[int, int]]] = {}
for _ps, _frames in _DATA["port_map"].items():
    _PORT_MAP[int(_ps)] = [(int(fr["can_id"], 16), fr["offset"]) for fr in _frames]

_MESSAGES: Dict[int, dict] = {}
for _cid_hex, _info in _DATA["messages"].items():
    _cid_int = int(_cid_hex, 16)
    sigs = []
    for s in _info["generic_signals"]:
        sigs.append((s["name"], s["startbit"], s["length"], s["factor"], s["offset"]))
    _MESSAGES[_cid_int] = {
        "name": _info["name"],
        "msg_type": _info["msg_type"],
        "pack_id": _info["pack_id"],
        "signals": sigs,
    }

_PORT_COLUMNS: Dict[int, List[str]] = {}
for _ps, _cols in _DATA["port_columns"].items():
    _PORT_COLUMNS[int(_ps)] = _cols

_ALL_PORTS = sorted(_PORT_MAP.keys())

_BASE_COLUMNS = ["timestamp", "source_port", "can_id_hex", "msg_type", "pack_id"]


@ParserRegistry.register
class BMS270VParser(BaseParser):
    parser_key = "bms_270v_v2.5"
    name = "270V&28V动力电池BMS"
    supported_ports: List[int] = _ALL_PORTS

    def can_parse_port(self, port: int) -> bool:
        return port in _PORT_MAP

    def get_output_columns(self, port: int) -> List[str]:
        return _PORT_COLUMNS.get(port, list(_BASE_COLUMNS))

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not payload:
            return None

        frame_list = _PORT_MAP.get(port)
        if not frame_list:
            return None

        rows: List[Dict[str, Any]] = []

        for expected_cid, byte_offset in frame_list:
            if byte_offset + 16 > len(payload):
                continue

            if not _can_frame_valid(payload, byte_offset, expected_cid):
                continue

            frame_bytes = payload[byte_offset: byte_offset + 16]
            can_data = frame_bytes[8:16]

            info = _MESSAGES.get(expected_cid)
            if not info:
                continue

            row: Dict[str, Any] = {
                "timestamp": timestamp,
                "source_port": port,
                "can_id_hex": f"0x{expected_cid:08X}",
                "msg_type": info["msg_type"],
                "pack_id": info["pack_id"],
            }

            for sig_name, startbit, bitlen, factor, offset in info["signals"]:
                raw = _extract_motorola(can_data, startbit, bitlen)
                if factor != 1.0 or offset != 0.0:
                    row[sig_name] = round(raw * factor + offset, 6)
                else:
                    row[sig_name] = raw

            rows.append(row)

        if not rows:
            return None

        if len(rows) == 1:
            return rows[0]

        first = rows[0].copy()
        first["_multi_rows"] = rows
        return first
