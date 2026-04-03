# -*- coding: utf-8 -*-
"""
ATG (CPE) 协议解析器

来源：CPE通信协议_标红必须-Label修改.docx
当前实现覆盖协议中标红必选的 9 个 Label:
- 132: Hybrid True Track Angle
- 175: Hybrid Ground Speed
- 254: Hybrid Latitude
- 255: Hybrid Longitude
- 261: Hybrid Altitude
- 324: Pitch Angle
- 325: Roll Angle
- 150: UTC
- 260: Date

输出字段单位（与协议 BNR/编码一致，见各 Label 在文档中的量纲）:
- true_track_angle_deg: 度 (°)
- ground_speed_kn: 节 (knots, kt)，地速
- latitude_deg / longitude_deg: 度 (°)
- altitude_ft: 英尺 (ft)，气压/混合高度（与 IRS 米制高度核对时需换算）
- pitch_angle_deg / roll_angle_deg: 度 (°)
"""
import re
import struct
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout
from .arinc429 import ARINC429Decoder


def _to_octal_label(label_str: str) -> Optional[int]:
    """将三位标签字符串转为十进制整数（优先按八进制解释）。"""
    if not label_str or len(label_str) != 3 or not label_str.isdigit():
        return None
    if all(ch in "01234567" for ch in label_str):
        return int(label_str, 8)
    return int(label_str)


_LABEL_STRINGS = ["132", "175", "254", "255", "261", "324", "325", "150", "260"]
_LABEL_MAP = {s: _to_octal_label(s) for s in _LABEL_STRINGS}
KNOWN_LABELS = {v for v in _LABEL_MAP.values() if v is not None}


def _extract_label_from_field_name(field_name: str) -> Optional[int]:
    """从字段名中提取 Label（三位数字），如 CPE_Label_132 / Label132 / L132。"""
    if not field_name:
        return None
    m = re.search(r"(\d{3})", field_name)
    if not m:
        return None
    return _to_octal_label(m.group(1))


@ParserRegistry.register
class ATGCPEParser(BaseParser):
    parser_key = "atg_cpe_v20260402"
    name = "ATG设备(CPE)"
    supported_ports: List[int] = []

    LABEL_TRACK_ANGLE = _LABEL_MAP["132"]
    LABEL_GROUND_SPEED = _LABEL_MAP["175"]
    LABEL_LATITUDE = _LABEL_MAP["254"]
    LABEL_LONGITUDE = _LABEL_MAP["255"]
    LABEL_ALTITUDE = _LABEL_MAP["261"]
    LABEL_PITCH = _LABEL_MAP["324"]
    LABEL_ROLL = _LABEL_MAP["325"]
    LABEL_UTC = _LABEL_MAP["150"]
    LABEL_DATE = _LABEL_MAP["260"]

    OUTPUT_COLUMNS = [
        "timestamp",
        "true_track_angle_deg",
        "ground_speed_kn",
        "latitude_deg",
        "longitude_deg",
        "altitude_ft",
        "pitch_angle_deg",
        "roll_angle_deg",
        "utc_time",
        "date_text",
        "utc_raw",
        "date_raw",
        "ssm_status",
    ]

    def __init__(self):
        self.decoder = ARINC429Decoder()

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[Dict[str, Any]]:
        if self.supported_ports and port not in self.supported_ports:
            return None
        if len(payload) < 4:
            return None

        if field_layout:
            return self._parse_with_layout(payload, timestamp, field_layout)
        return self._parse_with_scan(payload, timestamp)

    def _new_record(self, timestamp: float) -> Dict[str, Any]:
        out = {"timestamp": timestamp}
        for col in self.OUTPUT_COLUMNS:
            if col != "timestamp":
                out[col] = None
        return out

    def _parse_with_layout(
        self,
        payload: bytes,
        timestamp: float,
        field_layout: List[FieldLayout],
    ) -> Optional[Dict[str, Any]]:
        record = self._new_record(timestamp)
        ssm_statuses: List[int] = []
        hit = 0

        for field in field_layout:
            label = _extract_label_from_field_name(field.field_name)
            if label not in KNOWN_LABELS:
                continue
            if field.field_offset + field.field_length > len(payload):
                continue
            raw = payload[field.field_offset: field.field_offset + field.field_length]
            if len(raw) < 4:
                continue
            word = struct.unpack(">I", raw[:4])[0]
            if word == 0:
                continue
            self._apply_word(record, label, word)
            ssm_statuses.append(self.decoder.extract_ssm(word))
            hit += 1

        if hit == 0:
            return None
        if ssm_statuses:
            ok = ssm_statuses.count(0x03)
            record["ssm_status"] = f"{ok}/{len(ssm_statuses)} normal"
        return record

    def _parse_with_scan(self, payload: bytes, timestamp: float) -> Optional[Dict[str, Any]]:
        record = self._new_record(timestamp)
        ssm_statuses: List[int] = []
        hit = 0

        for offset in range(0, len(payload) - 3, 4):
            word = self.decoder.parse_word_from_bytes(payload, offset, "big")
            if word == 0:
                continue
            label = self.decoder.extract_label(word)
            if label not in KNOWN_LABELS:
                continue
            self._apply_word(record, label, word)
            ssm_statuses.append(self.decoder.extract_ssm(word))
            hit += 1

        if hit == 0:
            return None
        if ssm_statuses:
            ok = ssm_statuses.count(0x03)
            record["ssm_status"] = f"{ok}/{len(ssm_statuses)} normal"
        return record

    def _decode_signed_value(self, word: int, lsb: float, lsb_bit: int, msb_bit: int) -> float:
        data = self.decoder.extract_data_bits(word, lsb_bit, msb_bit)
        sign = self.decoder.extract_sign_bit(word)
        value = data * lsb
        if sign:
            value = -value
        return value

    def _decode_utc(self, word: int) -> str:
        # 协议为自定义二进制，按 HH:MM:SS 提取并做边界校验
        sec = self.decoder.extract_data_bits(word, 12, 17)
        minute = self.decoder.extract_data_bits(word, 18, 23)
        hour = self.decoder.extract_data_bits(word, 24, 28)
        if 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= sec <= 59:
            return f"{hour:02d}:{minute:02d}:{sec:02d}"
        return ""

    def _apply_word(self, record: Dict[str, Any], label: int, word: int) -> None:
        if label == self.LABEL_TRACK_ANGLE:
            record["true_track_angle_deg"] = self._decode_signed_value(word, 0.0054931640625, 14, 28)
        elif label == self.LABEL_GROUND_SPEED:
            record["ground_speed_kn"] = self.decoder.extract_data_bits(word, 14, 28) * 0.125
        elif label == self.LABEL_LATITUDE:
            record["latitude_deg"] = self._decode_signed_value(word, 0.000171661376953125, 9, 28)
        elif label == self.LABEL_LONGITUDE:
            record["longitude_deg"] = self._decode_signed_value(word, 0.000171661376953125, 9, 28)
        elif label == self.LABEL_ALTITUDE:
            record["altitude_ft"] = self._decode_signed_value(word, 0.125, 9, 28)
        elif label == self.LABEL_PITCH:
            record["pitch_angle_deg"] = self._decode_signed_value(word, 0.0054931640625, 14, 28)
        elif label == self.LABEL_ROLL:
            record["roll_angle_deg"] = self._decode_signed_value(word, 0.0054931640625, 14, 28)
        elif label == self.LABEL_UTC:
            record["utc_raw"] = hex(word)
            utc = self._decode_utc(word)
            if utc:
                record["utc_time"] = utc
        elif label == self.LABEL_DATE:
            # Date 编码在文档中存在多位复用说明，保留原始值并给出可读占位文本
            record["date_raw"] = hex(word)
            record["date_text"] = "from_label_260"

    def get_output_columns(self, port: int) -> List[str]:
        return self.OUTPUT_COLUMNS
