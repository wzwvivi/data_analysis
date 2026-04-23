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
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout

_BEIJING_TZ = timezone(timedelta(hours=8))

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
    display_name = "RTK 地基接收机"
    parser_version = "V1.4"
    protocol_family = "rtk"
    supported_ports = []

    # ---- 枚举映射表 ----
    _DEV_POS_MAP = {0b01: "左侧GPS1", 0b10: "右侧GPS2"}
    _FIX_VALID_MAP = {0b11: "有效", 0b01: "无效"}
    _SAT_SYS_MAP = {0: "无", 1: "GPS", 2: "北斗", 3: "组合"}
    _DOP_VALID_MAP = {0b11: "有效", 0b01: "无效"}
    _FIX_TYPE_MAP = {
        0x04: "无效解", 0x08: "单点定位",
        0x0C: "伪距差分", 0x15: "固定解", 0x0D: "浮点解",
    }
    _FAULT_01 = {0: "正常", 1: "故障"}

    # ---- 单位转换常量 ----
    _FT_TO_M = 0.3048
    _KN_TO_MS = 0.514444
    _NM_TO_KM = 1.852
    _FTMIN_TO_MS = 0.00508  # 1 ft/min = 0.3048/60 m/s

    OUTPUT_COLUMNS = [
        'timestamp', 'BeijingDateTime',
        'frame_count',
        # 枚举状态（原始值 + _enum）
        'equipment_location_number', 'equipment_location_number_enum',
        'locate_validity_flag', 'locate_validity_flag_enum',
        'satellite_system_flag', 'satellite_system_flag_enum',
        'DOP_validity_flag', 'DOP_validity_flag_enum',
        # GPS 有效性子字段
        'GPS_validity_insufNumSats', 'GPS_validity_insufNumSats_enum',
        'GPS_validity_noSbas', 'GPS_validity_noSbas_enum',
        'GPS_validity_paModeEnabled', 'GPS_validity_paModeEnabled_enum',
        'GPS_validity_posPartCorrected', 'GPS_validity_posPartCorrected_enum',
        'GPS_validity_posFullCorrected', 'GPS_validity_posFullCorrected_enum',
        'GPS_validity_posFullMonitored', 'GPS_validity_posFullMonitored_enum',
        'GPS_validity_posPaQualified', 'GPS_validity_posPaQualified_enum',
        # 接收机状态
        'receiver_positioning_status', 'receiver_positioning_status_enum',
        'num_sats_used', 'num_sats_visible',
        # DOP
        'hdop', 'vdop',
        # 位置 / 速度（英制 + 公制）
        'altitude_ft', 'altitude_m',
        'ellipsoid_height_ft', 'ellipsoid_height_m',
        'track_angle_deg',
        'ground_speed_kn', 'ground_speed_m_s',
        'latitude_deg', 'longitude_deg',
        # 保护级 + 故障标识（英制 + 公制）
        'hpl_sbas_nm', 'hpl_sbas_km', 'SBAS_flag', 'SBAS_flag_enum',
        'hpl_fd_nm', 'hpl_fd_km', 'HPL_FD_flag', 'HPL_FD_flag_enum',
        'vpl_sbas_ft', 'vpl_sbas_m',
        'vpl_fd_ft', 'vpl_fd_m',
        'vfom_ft', 'vfom_m',
        'hfom_nm', 'hfom_km',
        # 速度（英制 + 公制）
        'vertical_speed_ftmin', 'vertical_speed_m_s',
        'east_speed_kn', 'east_speed_m_s',
        'north_speed_kn', 'north_speed_m_s',
        # 维护故障
        'receiver_FaultFlags', 'receiver_FaultFlags_enum',
        # 精度（英制 + 公制）
        'vul_ft', 'vul_m',
        'hul_nm', 'hul_km',
        # UTC 时间（加工 + 原始分量）
        'utc_date', 'utc_date_year', 'utc_date_mon', 'utc_date_day',
        'utc_time', 'utc_time_hour', 'utc_time_min', 'utc_time_sec',
        'utc_day_second', 'utc_millisecond',
        # 版本
        'sw_version', 'hw_version',
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
        record: Dict[str, Any] = {'timestamp': timestamp}

        # BeijingDateTime
        try:
            dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            dt_bj = dt_utc.astimezone(_BEIJING_TZ)
            record['BeijingDateTime'] = dt_bj.strftime('%Y-%m-%d %H:%M:%S.') + f"{dt_bj.microsecond // 1000:03d}"
        except Exception:
            record['BeijingDateTime'] = ''

        # Word 1 (index 0): 帧头(已校验), 帧计数在 byte[1] 的低 8 bit
        record['frame_count'] = data[4] if len(data) > 4 else 0

        # ---- Word 2 (index 1) ----
        w2 = words[1]

        dev_pos = (w2 >> 30) & 0x03
        record['equipment_location_number'] = dev_pos
        record['equipment_location_number_enum'] = self._DEV_POS_MAP.get(dev_pos, f"未知({dev_pos})")

        fix_valid = (w2 >> 28) & 0x03
        record['locate_validity_flag'] = fix_valid
        record['locate_validity_flag_enum'] = self._FIX_VALID_MAP.get(fix_valid, f"未知({fix_valid})")

        sat_sys = (w2 >> 26) & 0x03
        record['satellite_system_flag'] = sat_sys
        record['satellite_system_flag_enum'] = self._SAT_SYS_MAP.get(sat_sys, f"未知({sat_sys})")

        dop_valid = (w2 >> 24) & 0x03
        record['DOP_validity_flag'] = dop_valid
        record['DOP_validity_flag_enum'] = self._DOP_VALID_MAP.get(dop_valid, f"未知({dop_valid})")

        # GPS 有效性 7 bit 拆分
        gps_v = (w2 >> 17) & 0x7F
        self._decode_gps_validity(record, gps_v)

        # 接收机状态
        rx_status = (w2 >> 2) & 0x7FFF
        fix_type_raw = (rx_status >> 10) & 0x1F
        record['receiver_positioning_status'] = fix_type_raw
        record['receiver_positioning_status_enum'] = self._FIX_TYPE_MAP.get(fix_type_raw, f"其他({fix_type_raw:#x})")
        record['num_sats_used'] = (rx_status >> 5) & 0x1F
        record['num_sats_visible'] = rx_status & 0x1F

        # ---- Word 3 (index 2): HDOP + VDOP ----
        w3 = words[2]
        record['hdop'] = ((w3 >> 16) & 0xFFFF) * 0.03125
        record['vdop'] = (w3 & 0xFFFF) * 0.03125

        # ---- Word 4-5: 海拔 / 椭球高度 ----
        alt = self._signed_bnr(words[3], 31, 21, 0.125)
        record['altitude_ft'] = alt
        record['altitude_m'] = alt * self._FT_TO_M
        eh = self._signed_bnr(words[4], 31, 21, 0.125)
        record['ellipsoid_height_ft'] = eh
        record['ellipsoid_height_m'] = eh * self._FT_TO_M

        # ---- Word 6: 航迹角 + 地速 ----
        w6 = words[5]
        record['track_angle_deg'] = self._signed_bnr_field((w6 >> 16) & 0xFFFF, 16, 180.0 / (2**15))
        gs = self._signed_bnr_field(w6 & 0xFFFF, 16, 0.125)
        record['ground_speed_kn'] = gs
        record['ground_speed_m_s'] = gs * self._KN_TO_MS

        # ---- Word 7-8: 纬度 / 经度 ----
        record['latitude_deg'] = self._signed_bnr_field(words[6], 32, 180.0 / (2**31))
        record['longitude_deg'] = self._signed_bnr_field(words[7], 32, 180.0 / (2**31))

        # ---- Word 9: HPL_SBAS + SBAS_flag (BIT32) ----
        hpl_sbas = self._unsigned_bnr_19(words[8], 16.0 / (2**17))
        record['hpl_sbas_nm'] = hpl_sbas
        record['hpl_sbas_km'] = hpl_sbas * self._NM_TO_KM
        sbas_f = (words[8] >> 31) & 0x01
        record['SBAS_flag'] = sbas_f
        record['SBAS_flag_enum'] = self._FAULT_01.get(sbas_f, str(sbas_f))

        # ---- Word 10: HPL_FD + HPL_FD_flag (BIT32) ----
        hpl_fd = self._unsigned_bnr_19(words[9], 16.0 / (2**17))
        record['hpl_fd_nm'] = hpl_fd
        record['hpl_fd_km'] = hpl_fd * self._NM_TO_KM
        fd_f = (words[9] >> 31) & 0x01
        record['HPL_FD_flag'] = fd_f
        record['HPL_FD_flag_enum'] = self._FAULT_01.get(fd_f, str(fd_f))

        # ---- Word 11-14: VPL_SBAS / VPL_FD / VFOM / HFOM ----
        vpl_sbas = self._unsigned_bnr_19(words[10], 0.125)
        record['vpl_sbas_ft'] = vpl_sbas
        record['vpl_sbas_m'] = vpl_sbas * self._FT_TO_M
        vpl_fd = self._unsigned_bnr_19(words[11], 0.125)
        record['vpl_fd_ft'] = vpl_fd
        record['vpl_fd_m'] = vpl_fd * self._FT_TO_M
        vfom = self._unsigned_bnr_19(words[12], 0.125)
        record['vfom_ft'] = vfom
        record['vfom_m'] = vfom * self._FT_TO_M
        hfom = self._unsigned_bnr_19(words[13], 16.0 / (2**18))
        record['hfom_nm'] = hfom
        record['hfom_km'] = hfom * self._NM_TO_KM

        # ---- Word 15: 天向速度 + 东向速度 ----
        w15 = words[14]
        vs = self._signed_bnr_field((w15 >> 16) & 0xFFFF, 16, 1.0)
        record['vertical_speed_ftmin'] = vs
        record['vertical_speed_m_s'] = vs * self._FTMIN_TO_MS
        es = self._signed_bnr_field(w15 & 0xFFFF, 16, 0.125)
        record['east_speed_kn'] = es
        record['east_speed_m_s'] = es * self._KN_TO_MS

        # ---- Word 16: 北向速度 + 维护故障字 ----
        w16 = words[15]
        ns = self._signed_bnr_field((w16 >> 16) & 0xFFFF, 16, 0.125)
        record['north_speed_kn'] = ns
        record['north_speed_m_s'] = ns * self._KN_TO_MS
        mf = w16 & 0xFFFF
        record['receiver_FaultFlags'] = mf
        record['receiver_FaultFlags_enum'] = "正常" if mf == 0 else "故障"

        # ---- Word 17-18: VUL / HUL ----
        vul = self._unsigned_bnr_19(words[16], 0.125)
        record['vul_ft'] = vul
        record['vul_m'] = vul * self._FT_TO_M
        hul = self._unsigned_bnr_19(words[17], 16.0 / (2**18))
        record['hul_nm'] = hul
        record['hul_km'] = hul * self._NM_TO_KM

        # ---- Word 19: 日期 ----
        w19 = words[18]
        day = (w19 >> 27) & 0x1F
        month = (w19 >> 23) & 0x0F
        year_hi = (w19 >> 16) & 0x7F
        year_lo = (w19 >> 9) & 0x7F
        year = year_hi * 100 + year_lo
        record['utc_date'] = f"{year:04d}-{month:02d}-{day:02d}" if month > 0 and day > 0 else "N/A"
        record['utc_date_year'] = year
        record['utc_date_mon'] = month
        record['utc_date_day'] = day

        # ---- Word 20: 时分秒 ----
        w20 = words[19]
        hour = (w20 >> 27) & 0x1F
        minute = (w20 >> 21) & 0x3F
        second = (w20 >> 15) & 0x3F
        record['utc_time'] = f"{hour:02d}:{minute:02d}:{second:02d}"
        record['utc_time_hour'] = hour
        record['utc_time_min'] = minute
        record['utc_time_sec'] = second

        # ---- Word 21: UTC日内秒 ----
        record['utc_day_second'] = (words[20] >> 15) & 0x1FFFF

        # ---- Word 22: 版本 ----
        w22 = words[21]
        record['sw_version'] = self._decode_version((w22 >> 16) & 0xFFFF, "SW")
        record['hw_version'] = self._decode_version(w22 & 0xFFFF, "HW")

        # ---- Word 23: UTC毫秒 ----
        record['utc_millisecond'] = (words[22] >> 16) & 0xFFFF

        return record

    def _decode_gps_validity(self, record: Dict[str, Any], gps_v: int) -> None:
        """拆分 GPS 有效性 7bit 为独立子字段"""
        fields = [
            ('GPS_validity_insufNumSats', 0, {0: "充足", 1: "不足"}),
            ('GPS_validity_noSbas', 1, {0: "已收到SBAS", 1: "未收到SBAS"}),
            ('GPS_validity_paModeEnabled', 2, {0: "未启用", 1: "已启用"}),
            ('GPS_validity_posPartCorrected', 3, {0: "未校正", 1: "已部分校正"}),
            ('GPS_validity_posFullCorrected', 4, {0: "未校正", 1: "已完全校正"}),
            ('GPS_validity_posFullMonitored', 5, {0: "未监控", 1: "全程监控"}),
            ('GPS_validity_posPaQualified', 6, {0: "不符合PA", 1: "符合PA"}),
        ]
        for col, bit, enum_map in fields:
            v = (gps_v >> bit) & 0x01
            record[col] = v
            record[col + '_enum'] = enum_map.get(v, str(v))

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
