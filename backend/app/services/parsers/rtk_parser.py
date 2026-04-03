# -*- coding: utf-8 -*-
"""
RTK 地基接收机解析器

根据《RTK设备通信协议（V1.4）》实现
数据帧结构：24组32bit数据（96字节），大端序
帧头: 0x55AA55AA

支持拼包解析：
TSN 网络包为 12 字节头 + 96 字节数据区（抓包常见总长 108 字节），
RS422 字节流中的 RTK 96字节帧可能跨越多个网络包。
需要将有效数据拼接后搜索帧头提取完整帧。

支持的数据字段：
- 状态: 设备位置, 定位有效性, 卫星系统, DOP有效性, 接收机状态
- DOP: HDOP, VDOP
- 位置: 纬度, 经度, 海拔高度, 椭球高度
- 速度: 地速, 航迹角, 天向速度, 东向速度, 北向速度
- 精度: HPL_SBAS, HPL_FD, VPL_SBAS, VPL_FD, VFOM, HFOM, VUL, HUL
- 时间: UTC日期, 时分秒, 日内秒
- 版本: 软件版本, 硬件版本

端口配置：动态端口，从TSN网络配置读取
"""
import struct
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout

FRAME_HEADER = 0x55AA55AA
FRAME_HEADER_BYTES = b'\x55\xAA\x55\xAA'
FRAME_LENGTH = 96  # 24 x 4 bytes

TSN_HEADER_LEN = 12
TSN_DATA_AREA_LEN = 96
TSN_VALID_FLAG_OFFSET = 4
TSN_DATA_LEN_OFFSET = 8


@ParserRegistry.register
class RTKParser(BaseParser):
    """RTK地基接收机解析器（支持拼包）"""

    parser_key = "rtk_v1.4"
    name = "RTK地基接收机"
    supported_ports = []

    OUTPUT_COLUMNS = [
        'timestamp',
        'device_position',
        'fix_valid',
        'sat_system',
        'dop_valid',
        'fix_type',
        'num_sats_used',
        'num_sats_visible',
        'hdop',
        'vdop',
        'altitude_ft',
        'ellipsoid_height_ft',
        'track_angle_deg',
        'ground_speed_kn',
        'latitude_deg',
        'longitude_deg',
        'hpl_sbas_nm',
        'hpl_fd_nm',
        'vpl_sbas_ft',
        'vpl_fd_ft',
        'vfom_ft',
        'hfom_nm',
        'vertical_speed_ftmin',
        'east_speed_kn',
        'north_speed_kn',
        'vul_ft',
        'hul_nm',
        'utc_date',
        'utc_time',
        'utc_day_second',
        'utc_millisecond',
        'sw_version',
        'hw_version',
        'gps_validity_raw',
        'maint_fault_raw',
    ]

    def __init__(self):
        self._port_buffers: Dict[int, bytearray] = {}
        self._port_timestamps: Dict[int, float] = {}

    def reset_buffers(self):
        """清空所有端口的拼包缓冲区"""
        self._port_buffers.clear()
        self._port_timestamps.clear()

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def feed_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> List[Dict[str, Any]]:
        """
        喂入一个 TSN 网络包，返回从拼包缓冲区中提取出的所有完整 RTK 帧解析结果。
        
        TSN 网络包固定 92 字节:
          [0-3]   协议填充 (4字节)
          [4-7]   有效位标识 (4字节, 0x03 = 有效)
          [8-11]  数据长度 (大端4字节, 值范围 0~80)
          [12-107] 数据区 (固定96字节, 前 data_len 字节有效, 其余填0)
        """
        results = []

        if len(payload) < TSN_HEADER_LEN:
            return results

        valid_flag = struct.unpack_from('<I', payload, TSN_VALID_FLAG_OFFSET)[0]
        if valid_flag != 0x03:
            return results

        data_len = struct.unpack_from('>I', payload, TSN_DATA_LEN_OFFSET)[0]
        if data_len == 0 or data_len > TSN_DATA_AREA_LEN:
            return results
        if TSN_HEADER_LEN + data_len > len(payload):
            return results

        effective_data = payload[TSN_HEADER_LEN:TSN_HEADER_LEN + data_len]

        if port not in self._port_buffers:
            self._port_buffers[port] = bytearray()

        self._port_buffers[port].extend(effective_data)
        self._port_timestamps[port] = timestamp

        results.extend(self._drain_buffer(port))
        return results

    def _drain_buffer(self, port: int) -> List[Dict[str, Any]]:
        """从缓冲区中尽可能多地提取完整 RTK 帧"""
        results = []
        buf = self._port_buffers[port]
        ts = self._port_timestamps[port]

        while len(buf) >= FRAME_LENGTH:
            idx = buf.find(FRAME_HEADER_BYTES)
            if idx < 0:
                if len(buf) >= 3 and buf[-3:] in (b'\x55\xAA\x55', b'\x55\xAA', b'\x55'):
                    pass
                else:
                    buf.clear()
                break

            if idx > 0:
                del buf[:idx]

            if len(buf) < FRAME_LENGTH:
                break

            frame = bytes(buf[:FRAME_LENGTH])
            del buf[:FRAME_LENGTH]

            try:
                record = self._parse_frame(frame, ts)
                results.append(record)
            except Exception:
                pass

        if len(buf) > FRAME_LENGTH * 4:
            del buf[:len(buf) - FRAME_LENGTH * 2]

        return results

    def flush_buffer(self, port: int) -> List[Dict[str, Any]]:
        """刷新指定端口的缓冲区，尝试提取剩余帧"""
        if port in self._port_buffers:
            return self._drain_buffer(port)
        return []

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[Dict[str, Any]]:
        """兼容接口：单包解析（不使用拼包）"""
        rtk_data = self._extract_rtk_data(payload, field_layout)
        if rtk_data is None:
            return None
        try:
            return self._parse_frame(rtk_data, timestamp)
        except Exception:
            return None

    def _extract_rtk_data(
        self,
        payload: bytes,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[bytes]:
        """从 payload 中提取 RTK 数据帧（仅用于单包解析兼容模式）"""
        if field_layout:
            for field in field_layout:
                if '422' in field.field_name or 'RTK' in field.field_name.upper():
                    offset = field.field_offset
                    if offset + FRAME_LENGTH <= len(payload):
                        candidate = payload[offset:offset + FRAME_LENGTH]
                        hdr = struct.unpack('>I', candidate[0:4])[0]
                        if hdr == FRAME_HEADER:
                            return candidate

        if len(payload) >= FRAME_LENGTH:
            hdr = struct.unpack('>I', payload[0:4])[0]
            if hdr == FRAME_HEADER:
                return payload[:FRAME_LENGTH]

        if len(payload) >= TSN_HEADER_LEN + FRAME_LENGTH:
            candidate = payload[TSN_HEADER_LEN:TSN_HEADER_LEN + FRAME_LENGTH]
            hdr = struct.unpack('>I', candidate[0:4])[0]
            if hdr == FRAME_HEADER:
                return candidate

        return None

    def _parse_frame(self, data: bytes, timestamp: float) -> Dict[str, Any]:
        words = struct.unpack('>24I', data)
        record = {'timestamp': timestamp}

        # Word 2 (index 1): 设备位置 + 定位有效 + 卫星系统 + DOP有效 + GPS有效性 + 接收机状态
        w2 = words[1]
        dev_pos = (w2 >> 30) & 0x03
        record['device_position'] = {0b01: "左侧GPS1", 0b10: "右侧GPS2"}.get(dev_pos, f"未知({dev_pos})")

        fix_valid = (w2 >> 28) & 0x03
        record['fix_valid'] = "有效" if fix_valid == 0b11 else "无效"

        sat_sys = (w2 >> 26) & 0x03
        record['sat_system'] = {0: "无", 1: "GPS", 2: "北斗", 3: "组合"}.get(sat_sys, f"未知({sat_sys})")

        dop_valid = (w2 >> 24) & 0x03
        record['dop_valid'] = "有效" if dop_valid == 0b11 else "无效"

        gps_validity = (w2 >> 17) & 0x7F
        record['gps_validity_raw'] = gps_validity

        rx_status = (w2 >> 2) & 0x7FFF
        fix_type_raw = (rx_status >> 10) & 0x1F
        record['fix_type'] = {
            0x04: "无效解", 0x08: "单点定位",
            0x0C: "伪距差分", 0x15: "固定解", 0x0D: "浮点解"
        }.get(fix_type_raw, f"其他({fix_type_raw:#x})")
        record['num_sats_used'] = (rx_status >> 5) & 0x1F
        record['num_sats_visible'] = rx_status & 0x1F

        # Word 3 (index 2): HDOP + VDOP
        w3 = words[2]
        hdop_raw = (w3 >> 16) & 0xFFFF
        vdop_raw = w3 & 0xFFFF
        record['hdop'] = hdop_raw * 0.03125
        record['vdop'] = vdop_raw * 0.03125

        # Word 4 (index 3): 海拔高度 (signed 21bit, BIT32-BIT12, res 0.125ft)
        record['altitude_ft'] = self._signed_bnr(words[3], 31, 21, 0.125)

        # Word 5 (index 4): 椭球高度
        record['ellipsoid_height_ft'] = self._signed_bnr(words[4], 31, 21, 0.125)

        # Word 6 (index 5): 航迹角(16bit high) + 地速(16bit low)
        w6 = words[5]
        record['track_angle_deg'] = self._signed_bnr_field((w6 >> 16) & 0xFFFF, 16, 180.0 / (2**15))
        record['ground_speed_kn'] = self._signed_bnr_field(w6 & 0xFFFF, 16, 0.125)

        # Word 7 (index 6): 纬度 (signed 32bit, res 180/2^31)
        record['latitude_deg'] = self._signed_bnr_field(words[6], 32, 180.0 / (2**31))

        # Word 8 (index 7): 经度
        record['longitude_deg'] = self._signed_bnr_field(words[7], 32, 180.0 / (2**31))

        # Word 9 (index 8): HPL_SBAS & 故障检测
        record['hpl_sbas_nm'] = self._unsigned_bnr_19(words[8], 16.0 / (2**17))

        # Word 10 (index 9): HPL_FD
        record['hpl_fd_nm'] = self._unsigned_bnr_19(words[9], 16.0 / (2**17))

        # Word 11 (index 10): VPL_SBAS
        record['vpl_sbas_ft'] = self._unsigned_bnr_19(words[10], 0.125)

        # Word 12 (index 11): VPL_FD
        record['vpl_fd_ft'] = self._unsigned_bnr_19(words[11], 0.125)

        # Word 13 (index 12): VFOM
        record['vfom_ft'] = self._unsigned_bnr_19(words[12], 0.125)

        # Word 14 (index 13): HFOM
        record['hfom_nm'] = self._unsigned_bnr_19(words[13], 16.0 / (2**18))

        # Word 15 (index 14): 天向速度(16bit high) + 东向速度(16bit low)
        w15 = words[14]
        record['vertical_speed_ftmin'] = self._signed_bnr_field((w15 >> 16) & 0xFFFF, 16, 1.0)
        record['east_speed_kn'] = self._signed_bnr_field(w15 & 0xFFFF, 16, 0.125)

        # Word 16 (index 15): 北向速度(16bit high) + 维护故障字(16bit low)
        w16 = words[15]
        record['north_speed_kn'] = self._signed_bnr_field((w16 >> 16) & 0xFFFF, 16, 0.125)
        record['maint_fault_raw'] = w16 & 0xFFFF

        # Word 17 (index 16): VUL
        record['vul_ft'] = self._unsigned_bnr_19(words[16], 0.125)

        # Word 18 (index 17): HUL
        record['hul_nm'] = self._unsigned_bnr_19(words[17], 16.0 / (2**18))

        # Word 19 (index 18): 日期
        w19 = words[18]
        day = (w19 >> 27) & 0x1F
        month = (w19 >> 23) & 0x0F
        year_hi = (w19 >> 16) & 0x7F
        year_lo = (w19 >> 9) & 0x7F
        year = year_hi * 100 + year_lo
        record['utc_date'] = f"{year:04d}-{month:02d}-{day:02d}" if month > 0 and day > 0 else "N/A"

        # Word 20 (index 19): 时分秒
        w20 = words[19]
        hour = (w20 >> 27) & 0x1F
        minute = (w20 >> 21) & 0x3F
        second = (w20 >> 15) & 0x3F
        record['utc_time'] = f"{hour:02d}:{minute:02d}:{second:02d}"

        # Word 21 (index 20): UTC日内秒
        w21 = words[20]
        record['utc_day_second'] = (w21 >> 15) & 0x1FFFF

        # Word 22 (index 21): 软件版本(16bit high) + 硬件版本(16bit low)
        w22 = words[21]
        record['sw_version'] = self._decode_version((w22 >> 16) & 0xFFFF, "SW")
        record['hw_version'] = self._decode_version(w22 & 0xFFFF, "HW")

        # Word 23 (index 22): UTC毫秒(16bit high) + 用户预留(16bit low)
        w23 = words[22]
        record['utc_millisecond'] = (w23 >> 16) & 0xFFFF

        return record

    @staticmethod
    def _signed_bnr(word: int, msb: int, nbits: int, resolution: float) -> float:
        """从32bit word中提取有符号BNR字段 (MSB对齐)"""
        shift = msb - nbits + 1
        mask = (1 << nbits) - 1
        raw = (word >> shift) & mask
        if raw & (1 << (nbits - 1)):
            raw -= (1 << nbits)
        return raw * resolution

    @staticmethod
    def _signed_bnr_field(raw: int, nbits: int, resolution: float) -> float:
        """对已提取的raw值做有符号转换"""
        if raw & (1 << (nbits - 1)):
            raw -= (1 << nbits)
        return raw * resolution

    @staticmethod
    def _unsigned_bnr_19(word: int, resolution: float) -> float:
        """提取BIT32-BIT14的19bit无符号字段 (BIT32=故障标识, BIT31-BIT14=18bit数据)"""
        raw_18 = (word >> 13) & 0x3FFFF
        return raw_18 * resolution

    @staticmethod
    def _decode_version(raw16: int, prefix: str) -> str:
        if prefix == "SW":
            vendor = (raw16 >> 10) & 0x03
            major = (raw16 >> 6) & 0x0F
            minor = raw16 & 0x3F
        else:
            vendor = (raw16 >> 10) & 0x03
            major = (raw16 >> 6) & 0x0F
            minor = raw16 & 0x3F
        return f"V{major}.{minor:03d}"

    def get_output_columns(self, port: int) -> List[str]:
        return self.OUTPUT_COLUMNS
