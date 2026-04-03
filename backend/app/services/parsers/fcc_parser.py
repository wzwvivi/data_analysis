# -*- coding: utf-8 -*-
"""
FCC 飞控解析器（飞控发出数据-TSN版-V13.4）

根据 ICD（网络交互数据 sheet），FCC 的 TSN 消息格式为：
  - Byte 0-3: 协议填充 (4B)
  - Byte 4-7: 功能状态集 (4B)
  - Byte 8+:  结构体Block（实际飞控数据）

飞控状态帧 (9001/9002/9003/9004):
  结构体 字节1 = 飞控表决结果 (uint8, bit mask)
    b0: FCC1  0-备 1-主
    b1: FCC2  0-备 1-主
    b2: FCC3  0-备 1-主
    b3: BCM   0-备 1-主

飞控通道选择 (9011/9012/9013/9014):
  结构体 字节1 = IRS通道选择 (uint8)
    0=惯导1  1=惯导2  2=惯导3
"""
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout

STATUS_PORTS = {9001: "FCC1", 9002: "FCC2", 9003: "FCC3", 9004: "BCM"}
CHANNEL_PORTS = {9011: "FCC1", 9012: "FCC2", 9013: "FCC3", 9014: "BCM"}
IRS_MAP = {0: "IRS1", 1: "IRS2", 2: "IRS3"}

TSN_HEADER_LEN = 8  # 协议填充(4B) + 功能状态集(4B)


def _decode_main_fcc(vote_byte: int) -> Optional[str]:
    """从飞控表决结果字节解码主飞控。bit mask: b0=FCC1, b1=FCC2, b2=FCC3, b3=BCM。"""
    if vote_byte & 0x01:
        return "FCC1"
    if vote_byte & 0x02:
        return "FCC2"
    if vote_byte & 0x04:
        return "FCC3"
    return None


@ParserRegistry.register
class FCCParser(BaseParser):
    parser_key = "fcc_v13"
    name = "FCC飞控数据"
    supported_ports: List[int] = []

    OUTPUT_COLUMNS = [
        "timestamp",
        "source_port",
        "source_fcc",
        "frame_type",
        "fcc_vote_raw",
        "fcc_vote_bits",
        "main_fcc",
        "irs_channel_code",
        "irs_channel_name",
        "raw_data",
        "packet_size",
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
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[Dict[str, Any]]:
        if not payload:
            return None

        out: Dict[str, Any] = {
            "timestamp": timestamp,
            "source_port": port,
            "source_fcc": STATUS_PORTS.get(port) or CHANNEL_PORTS.get(port),
            "frame_type": "other",
            "fcc_vote_raw": None,
            "fcc_vote_bits": None,
            "main_fcc": None,
            "irs_channel_code": None,
            "irs_channel_name": None,
            "raw_data": payload.hex(),
            "packet_size": len(payload),
        }

        if len(payload) <= TSN_HEADER_LEN:
            return out

        data = payload[TSN_HEADER_LEN:]
        b0 = int(data[0])

        if port in STATUS_PORTS:
            out["frame_type"] = "fcc_status"
            out["fcc_vote_raw"] = b0
            out["fcc_vote_bits"] = f"{b0:08b}"
            out["main_fcc"] = _decode_main_fcc(b0)
        elif port in CHANNEL_PORTS:
            out["frame_type"] = "fcc_channel_select"
            out["irs_channel_code"] = b0
            out["irs_channel_name"] = IRS_MAP.get(b0, f"UNKNOWN({b0})")

        return out

    def get_output_columns(self, port: int) -> List[str]:
        return self.OUTPUT_COLUMNS
