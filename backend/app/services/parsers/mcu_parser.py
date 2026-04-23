# -*- coding: utf-8 -*-
"""
MCU 电推电驱 CAN 解析器 (V6.0)

协议来源: 电推-电驱-CAN通信协议草案_251224_V6.0
端口映射来源: 转换后的ICD6.0.2（260317）
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseParser, ParserRegistry, FieldLayout
from .bms800v_parser import _can_frame_valid, _extract_can_data_from_frame

_DATA_DIR = Path(__file__).parent


def _load_data() -> dict:
    p = _DATA_DIR / "mcu_data.json"
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
    for s in _info.get("generic_signals", []):
        sigs.append((s["name"], s["startbit"], s["length"], s.get("factor", 1.0), s.get("offset", 0.0)))
    _MESSAGES[_cid_int] = {
        "name": _info.get("name", f"MSG_{_cid_hex[2:]}"),
        "msg_type": _info.get("msg_type", _info.get("name", f"MSG_{_cid_hex[2:]}")),
        "signals": sigs,
    }

_PORT_COLUMNS: Dict[int, List[str]] = {}
for _ps, _cols in _DATA["port_columns"].items():
    _PORT_COLUMNS[int(_ps)] = _cols

_ALL_PORTS = sorted(_PORT_MAP.keys())
_BASE_COLUMNS = ["timestamp", "source_port", "can_id_hex", "msg_name", "msg_type"]


def _extract_intel(data: bytes, startbit: int, length: int) -> int:
    """Extract unsigned value from 8-byte CAN data using Intel bit numbering."""
    if len(data) < 8:
        data = data + b"\x00" * (8 - len(data))
    raw = int.from_bytes(data[:8], "little", signed=False)
    mask = (1 << length) - 1
    return (raw >> startbit) & mask


@ParserRegistry.register
class MCUParser(BaseParser):
    parser_key = "mcu_v6.0"
    name = "MCU电推电驱"
    display_name = "MCU 电推电驱"
    parser_version = "V6.0"
    protocol_family = "mcu"
    supported_ports: List[int] = _ALL_PORTS

    def can_parse_port(self, port: int) -> bool:
        bundle = getattr(self, "_runtime_bundle", None)
        if bundle is not None:
            frames = bundle.can_frames_for(port)
            if frames:
                return True
        return port in _PORT_MAP

    def get_output_columns(self, port: int) -> List[str]:
        return _PORT_COLUMNS.get(port, list(_BASE_COLUMNS))

    def _get_can_frames(self, port: int) -> List[Tuple[int, int]]:
        """MR4: 端口→[(can_id_int, byte_offset)]，bundle 优先、硬编码兜底。"""
        bundle = getattr(self, "_runtime_bundle", None)
        if bundle is not None:
            frames = bundle.can_frames_for(port)
            if frames:
                return [(int(c), int(o)) for c, o in frames]
        return _PORT_MAP.get(port) or []

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not payload:
            return None

        frame_list = self._get_can_frames(port)
        if not frame_list:
            return None

        rows: List[Dict[str, Any]] = []

        for expected_cid, byte_offset in frame_list:
            if byte_offset + 16 > len(payload):
                continue

            if not _can_frame_valid(payload, byte_offset, expected_cid):
                continue

            frame_bytes = payload[byte_offset: byte_offset + 16]
            can_data = _extract_can_data_from_frame(frame_bytes)

            info = _MESSAGES.get(expected_cid)
            if not info:
                continue

            row: Dict[str, Any] = {
                "timestamp": timestamp,
                "source_port": port,
                "can_id_hex": f"0x{expected_cid:08X}",
                "msg_name": info["name"],
                "msg_type": info["msg_type"],
            }

            for sig_name, startbit, bitlen, factor, offset in info["signals"]:
                raw = _extract_intel(can_data, startbit, bitlen)
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
