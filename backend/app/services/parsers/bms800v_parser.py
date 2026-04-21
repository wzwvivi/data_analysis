# -*- coding: utf-8 -*-
"""
800V 动力电池 BMS CAN 解析器 (V2.6)

TSN 包结构:
  Byte 0-3 : 协议填充 (4B)
  Byte 4-7 : 功能状态集 (4B)
  Byte 8+  : CAN_FRAME 序列, 每帧 16B, 每 4 帧后插入 4B 功能状态集

CAN_FRAME (16B):
  Byte 0-3 : CAN 仲裁域 (wire format, big-endian)
              Extended frame: BaseID(11)|SRR(1)|IDE(1)|ExtID(18)|RTR(1)
  Byte 4-7 : DLC / 状态
  Byte 8-15: 8B CAN 数据

TSN 存储的 4 字节是 CAN 总线线上格式 (wire format), 不是标准 29-bit CAN-ID.
需要通过 decode_can_wire_id() 转换后才能与 ICD 定义的 CAN-ID 比较.

信号: Motorola byte-order, Unsigned, 物理值 = raw * factor + offset
输出: 通用列名 + pack_id 区分电池包
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from .base import BaseParser, ParserRegistry, FieldLayout

_DATA_DIR = Path(__file__).parent


def _load_data() -> dict:
    p = _DATA_DIR / "bms800v_data.json"
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


def _extract_motorola(data: bytes, startbit: int, length: int) -> int:
    """Extract unsigned value from 8-byte CAN data using Motorola bit numbering.

    Motorola startbit = MSB position.  Bit numbering:
      byte0=[7..0], byte1=[15..8], byte2=[23..16], ...
    """
    if len(data) < 8:
        data = data + b"\x00" * (8 - len(data))

    value = int.from_bytes(data[:8], "big")

    cur_byte = startbit // 8
    cur_bit = startbit % 8
    result = 0

    for _ in range(length):
        bit_pos = (7 - cur_byte) * 8 + cur_bit
        result = (result << 1) | ((value >> bit_pos) & 1)
        cur_bit -= 1
        if cur_bit < 0:
            cur_byte += 1
            cur_bit = 7

    return result


_BASE_COLUMNS = ["timestamp", "source_port", "can_id_hex", "msg_type", "pack_id"]

import struct

_VALID_STATUS = 0x03
_PROTOCOL_PAD_LEN = 4
_STATUS_LEN = 4
_FRAME_LEN = 16
_GROUP_FRAMES = 4
_GROUP_DATA_LEN = _STATUS_LEN + _FRAME_LEN * _GROUP_FRAMES  # 68


def decode_can_wire_id(wire_32: int) -> int:
    """Decode TSN CAN wire-format 32-bit value to standard 29-bit CAN-ID.

    TSN stores the CAN extended frame arbitration field in bus wire order:
      Bit[31:21] = Base ID  (ID[28:18], 11 bits)
      Bit[20]    = SRR
      Bit[19]    = IDE
      Bit[18:1]  = Extended ID (ID[17:0], 18 bits)
      Bit[0]     = RTR
    """
    base_id = (wire_32 >> 21) & 0x7FF
    ext_id = (wire_32 >> 1) & 0x3FFFF
    return (base_id << 18) | ext_id


def encode_can_wire_id(can_id_29: int, rtr: int = 0) -> int:
    """Encode standard 29-bit CAN-ID to TSN wire-format 32-bit value."""
    base_id = (can_id_29 >> 18) & 0x7FF
    ext_id = can_id_29 & 0x3FFFF
    return (base_id << 21) | (1 << 20) | (1 << 19) | (ext_id << 1) | rtr


def _can_frame_valid(payload: bytes, byte_offset: int, expected_cid: int) -> bool:
    """Check status-set validity and CAN-ID match for a frame at byte_offset.

    The expected_cid is the standard 29-bit CAN-ID from the ICD.
    The actual 4 bytes in the payload are in CAN wire format and must be
    decoded before comparison.
    """
    frame_idx_in_payload = byte_offset - _PROTOCOL_PAD_LEN - _STATUS_LEN
    if frame_idx_in_payload < 0:
        return True
    group_idx = frame_idx_in_payload // (_FRAME_LEN * _GROUP_FRAMES + _STATUS_LEN)
    slot_in_group = (frame_idx_in_payload - group_idx * (_FRAME_LEN * _GROUP_FRAMES + _STATUS_LEN)) // _FRAME_LEN
    status_offset = _PROTOCOL_PAD_LEN + group_idx * _GROUP_DATA_LEN
    if status_offset + _STATUS_LEN > len(payload):
        return True
    if slot_in_group < 0 or slot_in_group >= _STATUS_LEN:
        return True
    if payload[status_offset + slot_in_group] != _VALID_STATUS:
        return False
    wire_val = struct.unpack_from(">I", payload, byte_offset)[0]
    if wire_val == 0:
        return False
    actual_cid = decode_can_wire_id(wire_val)
    if actual_cid != expected_cid:
        return False
    return True


@ParserRegistry.register
class BMS800VParser(BaseParser):
    parser_key = "bms_800v_v2.5"
    name = "800V动力电池BMS"
    supported_ports: List[int] = _ALL_PORTS

    def can_parse_port(self, port: int) -> bool:
        # MR4: 优先问 bundle；未注入时回落到模块级 _PORT_MAP
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
