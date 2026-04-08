# -*- coding: utf-8 -*-
"""
S模式应答机（JZXPDR113B）专用解析器

实现依据：JZXPDR113B S模式应答机接口控制文件（20260113 版）
解析ARINC 429数据流，端口由TSN网络配置动态指定

========== 输入标号 (→ ATC) ==========
- 306: 设置工作状态 (离散量, TACU→ATC)
- 031: 设置应答代码 (BCD, TACU→ATC)
- 331: 设置S模式地址1 (BNR, AOT→ATC)
- 332: 设置S模式地址2 (BNR, AOT→ATC)
- 261: 设置当前航班号1 (BNR, FMS→ATC)
- 235: 设置当前航班号2 (BNR, FMS→ATC)
- 236: 设置当前航班号3 (BNR, FMS→ATC)
- 203: 绝对气压高度 (BNR, ADC1→ATC)
- 210: 真空速 (BNR, ADC1→ATC)
- 212: 升降速度 (BNR, ADC1→ATC)
- 125: 北京时间 (BCD, TBD→ATC)
- 310: 即时位置纬度 高20位 (BNR)
- 313: 即时位置纬度 低11位 (BNR)
- 311: 即时位置经度 高20位 (BNR)
- 317: 即时位置经度 低11位 (BNR)
- 312: 地速 (BNR)
- 314: 真航向 (BNR)
- 322: 真航迹角 (BNR)
- 365: 天向速度 (BNR)
- 366: 北向速度 (BNR)
- 367: 东向速度 (BNR)
- 361: 几何高度 (BNR)
- 267: 导航完整性信息 (BCD)

========== 输出标号 (ATC →) ==========
- 306: 工作状态回传 (离散量, ATC→TACU)
- 031: 返回当前识别代码 (BCD, ATC→TACU)
- 331: 返回S模式地址1 (BNR, ATC→AOT)
- 332: 返回S模式地址2 (BNR, ATC→AOT)
- 261: 返回当前航班号1 (BNR, ATC→FMS)
- 235: 返回当前航班号2 (BNR, ATC→FMS)
- 236: 返回当前航班号3 (BNR, ATC→FMS)
- 133: 入侵机真航向 (BNR, ATC→DCU)
- 162: 入侵机识别代码 (BCD, ATC→DCU)
- 134: 入侵机航班号1 (BNR, ATC→DCU)
- 135: 入侵机航班号2 (BNR, ATC→DCU)
- 136: 入侵机航班号3 (BNR, ATC→DCU)
- 137: 入侵机航班号4 (BNR, ATC→DCU)
- 141: 入侵机地速 (BNR, ATC→DCU)
- 142: 入侵机纬度高12位 (BNR, ATC→DCU)
- 143: 入侵机纬度低12位 (BNR, ATC→DCU)
- 144: 入侵机经度高12位 (BNR, ATC→DCU)
- 145: 入侵机经度低12位 (BNR, ATC→DCU)
- 146: 入侵机S模式地址高12位 (BNR, ATC→DCU)
- 147: 入侵机S模式地址低12位 (BNR, ATC→DCU)
- 151: 入侵机垂直速度 (BNR, ATC→DCU)
- 152: 入侵机北向速度 (BNR, ATC→DCU)
- 153: 入侵机东向速度 (BNR, ATC→DCU)
- 154: 入侵机导航精度类别 (BNR, ATC→DCU)
- 155: 入侵机导航完整性类别 (BNR, ATC→DCU)
- 156: 入侵机状况消息 (BNR, ATC→DCU)
- 157: 入侵机高度 (BNR, ATC→DCU)
- 160: 入侵机时标1 (BNR, ATC→DCU)
- 161: 入侵机时标2 (BNR, ATC→DCU)
- 357: 发送起始/终止字 (BNR, ATC→DCU)
- 233: 软件版本号 (BCD, ATC→OMS)
- 234: 软件版本日期 (BCD, ATC→OMS)
"""
import struct
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout
from .arinc429 import ARINC429Decoder
from .arinc429_mixin import (
    Arinc429Mixin, build_field_name_to_label, SKIP_FIELDS, TSN_HEADER_LEN,
)


_LABEL_OCTAL_MAP = {
    '306': 0o306,  '031': 0o031,  '331': 0o331,  '332': 0o332,
    '261': 0o261,  '235': 0o235,  '236': 0o236,  '203': 0o203,
    '210': 0o210,  '212': 0o212,  '125': 0o125,  '310': 0o310,
    '313': 0o313,  '311': 0o311,  '317': 0o317,  '312': 0o312,
    '314': 0o314,  '322': 0o322,  '365': 0o365,  '366': 0o366,
    '367': 0o367,  '361': 0o361,  '267': 0o267,
    '133': 0o133,  '162': 0o162,  '134': 0o134,  '135': 0o135,
    '136': 0o136,  '137': 0o137,  '141': 0o141,  '142': 0o142,
    '143': 0o143,  '144': 0o144,  '145': 0o145,  '146': 0o146,
    '147': 0o147,  '151': 0o151,  '152': 0o152,  '153': 0o153,
    '154': 0o154,  '155': 0o155,  '156': 0o156,  '157': 0o157,
    '160': 0o160,  '161': 0o161,  '357': 0o357,  '233': 0o233,
    '234': 0o234,
}

_LABEL_DEFS: Dict[int, dict] = {v: {} for v in _LABEL_OCTAL_MAP.values()}

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)

ALL_KNOWN_LABELS = set(_LABEL_OCTAL_MAP.values())


@ParserRegistry.register
class JZXPDR113BParser(Arinc429Mixin, BaseParser):
    """S模式应答机解析器（内部标识 jzxpdr113b_v20260113）"""

    parser_key = "jzxpdr113b_v20260113"
    name = "S模式应答机"
    supported_ports = []

    _LABEL_DEFS = _LABEL_DEFS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL
    _PORT_LABELS = None

    # ---- 输入标号 ----
    LABEL_WORK_STATUS = 0o306
    LABEL_SQUAWK_CODE = 0o031
    LABEL_SMODE_ADDR1 = 0o331
    LABEL_SMODE_ADDR2 = 0o332
    LABEL_FLIGHT_ID1 = 0o261
    LABEL_FLIGHT_ID2 = 0o235
    LABEL_FLIGHT_ID3 = 0o236
    LABEL_BARO_ALT = 0o203
    LABEL_TRUE_AIRSPEED = 0o210
    LABEL_VERT_RATE = 0o212
    LABEL_BJT = 0o125
    LABEL_LAT_HIGH = 0o310
    LABEL_LAT_LOW = 0o313
    LABEL_LON_HIGH = 0o311
    LABEL_LON_LOW = 0o317
    LABEL_GROUND_SPEED = 0o312
    LABEL_TRUE_HEADING = 0o314
    LABEL_TRACK_ANGLE = 0o322
    LABEL_VERT_VELOCITY = 0o365
    LABEL_NORTH_VELOCITY = 0o366
    LABEL_EAST_VELOCITY = 0o367
    LABEL_GEO_HEIGHT = 0o361
    LABEL_NAV_INTEGRITY = 0o267

    # ---- 输出标号（ATC发出） ----
    LABEL_INTRUDER_HEADING = 0o133
    LABEL_INTRUDER_SQUAWK = 0o162
    LABEL_INTRUDER_FLT1 = 0o134
    LABEL_INTRUDER_FLT2 = 0o135
    LABEL_INTRUDER_FLT3 = 0o136
    LABEL_INTRUDER_FLT4 = 0o137
    LABEL_INTRUDER_GS = 0o141
    LABEL_INTRUDER_LAT_H = 0o142
    LABEL_INTRUDER_LAT_L = 0o143
    LABEL_INTRUDER_LON_H = 0o144
    LABEL_INTRUDER_LON_L = 0o145
    LABEL_INTRUDER_ADDR_H = 0o146
    LABEL_INTRUDER_ADDR_L = 0o147
    LABEL_INTRUDER_VS = 0o151
    LABEL_INTRUDER_NV = 0o152
    LABEL_INTRUDER_EV = 0o153
    LABEL_INTRUDER_NAC = 0o154
    LABEL_INTRUDER_NIC = 0o155
    LABEL_INTRUDER_STATUS = 0o156
    LABEL_INTRUDER_ALT = 0o157
    LABEL_INTRUDER_TS1 = 0o160
    LABEL_INTRUDER_TS2 = 0o161
    LABEL_START_STOP = 0o357
    LABEL_SW_VERSION = 0o233
    LABEL_SW_DATE = 0o234

    OUTPUT_COLUMNS = [
        'timestamp',
        'work_status_raw',
        'squawk_code',
        'smode_addr_low_raw',
        'smode_addr_high_raw',
        'flight_id_part1',
        'flight_id_part2',
        'flight_id_part3',
        'baro_altitude_ft',
        'true_airspeed_kn',
        'vertical_rate_ftmin',
        'beijing_time',
        'latitude',
        'longitude',
        'ground_speed',
        'true_heading',
        'track_angle',
        'vertical_velocity',
        'north_velocity',
        'east_velocity',
        'geometric_height',
        'nav_integrity_raw',
        'intruder_heading',
        'intruder_squawk',
        'intruder_flt1_raw',
        'intruder_flt2_raw',
        'intruder_flt3_raw',
        'intruder_flt4_raw',
        'intruder_gs',
        'intruder_lat_h_raw',
        'intruder_lat_l_raw',
        'intruder_lon_h_raw',
        'intruder_lon_l_raw',
        'intruder_addr_h_raw',
        'intruder_addr_l_raw',
        'intruder_vs',
        'intruder_nv',
        'intruder_ev',
        'intruder_nac_raw',
        'intruder_nic_raw',
        'intruder_status_raw',
        'intruder_alt',
        'intruder_ts1_raw',
        'intruder_ts2_raw',
        'start_stop_raw',
        'sw_version',
        'sw_date',
        'ssm_status',
    ]

    _OUTPUT_COLUMNS = OUTPUT_COLUMNS

    def __init__(self):
        self._mixin_init()
        self._pending_data: Dict[str, Any] = {}
        self._lat_high_word: Optional[int] = None
        self._lat_low_word: Optional[int] = None
        self._lon_high_word: Optional[int] = None
        self._lon_low_word: Optional[int] = None
        self._ssm_statuses: List[int] = []

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def get_output_columns(self, port: int) -> List[str]:
        return self.OUTPUT_COLUMNS

    _layout_debug_logged = set()

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

        self._lat_high_word = None
        self._lat_low_word = None
        self._lon_high_word = None
        self._lon_low_word = None
        self._ssm_statuses = []

        if field_layout:
            if port not in self._layout_debug_logged:
                self._layout_debug_logged.add(port)
                matched = [f.field_name for f in field_layout if f.field_name in _FIELD_NAME_TO_LABEL]
                print(f"[JZXPDR113B] 端口 {port}: 布局字段 {len(field_layout)} 个, "
                      f"匹配 {len(matched)} 个")
            return self._parse_with_layout(payload, port, timestamp, field_layout)
        else:
            return self._parse_with_scan(payload, port, timestamp)

    def _parse_with_scan(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
    ) -> Optional[Dict[str, Any]]:
        if len(payload) < TSN_HEADER_LEN + 4:
            return None

        port_cols = self.get_output_columns(port)
        data = payload[TSN_HEADER_LEN:]
        record: Dict[str, Any] = {c: None for c in port_cols}
        record["timestamp"] = timestamp
        found_any = False

        offset = 0
        while offset + 4 <= len(data):
            word = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

            if word == 0:
                continue

            label = self.decoder.extract_label(word)

            if label not in ALL_KNOWN_LABELS:
                continue

            self._ssm_statuses.append(self.decoder.extract_ssm(word))
            found_any = True
            self._decode_word(record, word, label)

            if label == self.LABEL_LAT_HIGH:
                self._lat_high_word = word
            elif label == self.LABEL_LAT_LOW:
                self._lat_low_word = word
            elif label == self.LABEL_LON_HIGH:
                self._lon_high_word = word
            elif label == self.LABEL_LON_LOW:
                self._lon_low_word = word

        if found_any:
            self._post_process(record)
            return record
        return None

    def _post_process(self, record: Dict[str, Any]) -> None:
        self._merge_lat_lon(record)
        if self._ssm_statuses:
            normal_count = self._ssm_statuses.count(0x03)
            record['ssm_status'] = f"{normal_count}/{len(self._ssm_statuses)} normal"

    def _init_record(self, timestamp: float) -> Dict[str, Any]:
        record: Dict[str, Any] = {'timestamp': timestamp}
        for col in self.OUTPUT_COLUMNS:
            if col != 'timestamp':
                record[col] = None
        return record

    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        decoded = self._decode_label(label, word)

        ssm = self.decoder.extract_ssm(word)
        if label not in (self.LABEL_LAT_HIGH, self.LABEL_LAT_LOW,
                         self.LABEL_LON_HIGH, self.LABEL_LON_LOW):
            if ssm not in [s for s in self._ssm_statuses]:
                pass

        self._apply_decoded(record, label, word, decoded)

        if label == self.LABEL_LAT_HIGH:
            self._lat_high_word = word
        elif label == self.LABEL_LAT_LOW:
            self._lat_low_word = word
        elif label == self.LABEL_LON_HIGH:
            self._lon_high_word = word
        elif label == self.LABEL_LON_LOW:
            self._lon_low_word = word

    def _apply_decoded(self, record, label_octal, word, decoded):
        d = self.decoder

        if label_octal == self.LABEL_WORK_STATUS:
            record['work_status_raw'] = hex(word)
        elif label_octal == self.LABEL_SQUAWK_CODE:
            record['squawk_code'] = decoded
        elif label_octal == self.LABEL_SMODE_ADDR1:
            record['smode_addr_low_raw'] = hex(word)
        elif label_octal == self.LABEL_SMODE_ADDR2:
            record['smode_addr_high_raw'] = hex(word)
        elif label_octal == self.LABEL_FLIGHT_ID1:
            record['flight_id_part1'] = decoded
        elif label_octal == self.LABEL_FLIGHT_ID2:
            record['flight_id_part2'] = decoded
        elif label_octal == self.LABEL_FLIGHT_ID3:
            record['flight_id_part3'] = decoded
        elif label_octal == self.LABEL_BARO_ALT:
            record['baro_altitude_ft'] = decoded
        elif label_octal == self.LABEL_TRUE_AIRSPEED:
            record['true_airspeed_kn'] = decoded
        elif label_octal == self.LABEL_VERT_RATE:
            record['vertical_rate_ftmin'] = decoded
        elif label_octal == self.LABEL_BJT:
            record['beijing_time'] = decoded
        elif label_octal == self.LABEL_GROUND_SPEED:
            record['ground_speed'] = decoded
        elif label_octal == self.LABEL_TRUE_HEADING:
            record['true_heading'] = decoded
        elif label_octal == self.LABEL_TRACK_ANGLE:
            record['track_angle'] = decoded
        elif label_octal == self.LABEL_VERT_VELOCITY:
            record['vertical_velocity'] = decoded
        elif label_octal == self.LABEL_NORTH_VELOCITY:
            record['north_velocity'] = decoded
        elif label_octal == self.LABEL_EAST_VELOCITY:
            record['east_velocity'] = decoded
        elif label_octal == self.LABEL_GEO_HEIGHT:
            record['geometric_height'] = decoded
        elif label_octal == self.LABEL_NAV_INTEGRITY:
            record['nav_integrity_raw'] = hex(word)
        elif label_octal == self.LABEL_INTRUDER_HEADING:
            record['intruder_heading'] = decoded
        elif label_octal == self.LABEL_INTRUDER_SQUAWK:
            record['intruder_squawk'] = decoded
        elif label_octal == self.LABEL_INTRUDER_FLT1:
            record['intruder_flt1_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_FLT2:
            record['intruder_flt2_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_FLT3:
            record['intruder_flt3_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_FLT4:
            record['intruder_flt4_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_GS:
            record['intruder_gs'] = decoded
        elif label_octal == self.LABEL_INTRUDER_LAT_H:
            record['intruder_lat_h_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_LAT_L:
            record['intruder_lat_l_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_LON_H:
            record['intruder_lon_h_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_LON_L:
            record['intruder_lon_l_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_ADDR_H:
            record['intruder_addr_h_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_ADDR_L:
            record['intruder_addr_l_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_VS:
            record['intruder_vs'] = decoded
        elif label_octal == self.LABEL_INTRUDER_NV:
            record['intruder_nv'] = decoded
        elif label_octal == self.LABEL_INTRUDER_EV:
            record['intruder_ev'] = decoded
        elif label_octal == self.LABEL_INTRUDER_NAC:
            record['intruder_nac_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_NIC:
            record['intruder_nic_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_STATUS:
            record['intruder_status_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_ALT:
            record['intruder_alt'] = decoded
        elif label_octal == self.LABEL_INTRUDER_TS1:
            record['intruder_ts1_raw'] = decoded
        elif label_octal == self.LABEL_INTRUDER_TS2:
            record['intruder_ts2_raw'] = decoded
        elif label_octal == self.LABEL_START_STOP:
            record['start_stop_raw'] = decoded
        elif label_octal == self.LABEL_SW_VERSION:
            record['sw_version'] = decoded
        elif label_octal == self.LABEL_SW_DATE:
            record['sw_date'] = decoded

    def _decode_label(self, label_octal: int, word: int) -> Any:
        d = self.decoder

        if label_octal == self.LABEL_WORK_STATUS:
            return d.decode_work_status_306(word)
        elif label_octal == self.LABEL_SQUAWK_CODE:
            return d.decode_squawk_code(word)
        elif label_octal == self.LABEL_SMODE_ADDR1:
            return d.decode_smode_addr_low(word)
        elif label_octal == self.LABEL_SMODE_ADDR2:
            return d.decode_smode_addr_high(word)
        elif label_octal == self.LABEL_FLIGHT_ID1:
            return d.decode_flight_id_1(word)
        elif label_octal == self.LABEL_FLIGHT_ID2:
            return d.decode_flight_id_2(word)
        elif label_octal == self.LABEL_FLIGHT_ID3:
            return d.decode_flight_id_3(word)
        elif label_octal == self.LABEL_BARO_ALT:
            return d.decode_barometric_altitude(word)
        elif label_octal == self.LABEL_TRUE_AIRSPEED:
            return d.decode_true_airspeed(word)
        elif label_octal == self.LABEL_VERT_RATE:
            return d.decode_vertical_rate(word)
        elif label_octal == self.LABEL_BJT:
            hours, minutes, seconds = d.decode_beijing_time(word)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        elif label_octal == self.LABEL_GROUND_SPEED:
            return d.decode_ground_speed(word)
        elif label_octal == self.LABEL_TRUE_HEADING:
            return d.decode_true_heading(word)
        elif label_octal == self.LABEL_TRACK_ANGLE:
            return d.decode_track_angle(word)
        elif label_octal == self.LABEL_VERT_VELOCITY:
            return d.decode_vertical_velocity(word)
        elif label_octal == self.LABEL_NORTH_VELOCITY:
            return d.decode_north_velocity(word)
        elif label_octal == self.LABEL_EAST_VELOCITY:
            return d.decode_east_velocity(word)
        elif label_octal == self.LABEL_GEO_HEIGHT:
            return d.decode_geometric_height(word)
        elif label_octal == self.LABEL_NAV_INTEGRITY:
            return hex(word)
        elif label_octal in (self.LABEL_LAT_HIGH, self.LABEL_LAT_LOW,
                             self.LABEL_LON_HIGH, self.LABEL_LON_LOW):
            return word
        elif label_octal == self.LABEL_INTRUDER_HEADING:
            return d.decode_intruder_heading(word)
        elif label_octal == self.LABEL_INTRUDER_SQUAWK:
            return d.decode_intruder_squawk(word)
        elif label_octal in (self.LABEL_INTRUDER_FLT1, self.LABEL_INTRUDER_FLT2,
                             self.LABEL_INTRUDER_FLT3, self.LABEL_INTRUDER_FLT4):
            return d.decode_intruder_flight_id(word)
        elif label_octal == self.LABEL_INTRUDER_GS:
            return d.decode_intruder_ground_speed(word)
        elif label_octal in (self.LABEL_INTRUDER_LAT_H, self.LABEL_INTRUDER_LAT_L):
            return d.decode_intruder_lat_lon_12bit(word)
        elif label_octal in (self.LABEL_INTRUDER_LON_H, self.LABEL_INTRUDER_LON_L):
            return d.decode_intruder_lat_lon_12bit(word)
        elif label_octal in (self.LABEL_INTRUDER_ADDR_H, self.LABEL_INTRUDER_ADDR_L):
            return d.decode_intruder_smode_addr_12bit(word)
        elif label_octal == self.LABEL_INTRUDER_VS:
            return d.decode_intruder_vert_speed(word)
        elif label_octal in (self.LABEL_INTRUDER_NV, self.LABEL_INTRUDER_EV):
            return d.decode_intruder_velocity(word)
        elif label_octal in (self.LABEL_INTRUDER_NAC, self.LABEL_INTRUDER_NIC):
            return d.decode_intruder_nav_category(word)
        elif label_octal == self.LABEL_INTRUDER_STATUS:
            return d.decode_intruder_status(word)
        elif label_octal == self.LABEL_INTRUDER_ALT:
            return d.decode_intruder_altitude(word)
        elif label_octal in (self.LABEL_INTRUDER_TS1, self.LABEL_INTRUDER_TS2):
            return d.decode_intruder_timestamp(word)
        elif label_octal == self.LABEL_START_STOP:
            return d.decode_start_stop_word(word)
        elif label_octal == self.LABEL_SW_VERSION:
            return d.decode_software_version(word)
        elif label_octal == self.LABEL_SW_DATE:
            return d.decode_software_date(word)

        return None

    def _merge_lat_lon(self, record: Dict):
        if self._lat_high_word is not None and self._lat_low_word is not None:
            record['latitude'] = self.decoder.combine_latitude(self._lat_high_word, self._lat_low_word)
        elif self._lat_high_word is not None:
            high_data, sign = self.decoder.decode_latitude_high(self._lat_high_word)
            lsb = 0.0000000838 * (1 << 11)
            record['latitude'] = high_data * lsb * (-1 if sign else 1)

        if self._lon_high_word is not None and self._lon_low_word is not None:
            record['longitude'] = self.decoder.combine_longitude(self._lon_high_word, self._lon_low_word)
        elif self._lon_high_word is not None:
            high_data, sign = self.decoder.decode_longitude_high(self._lon_high_word)
            lsb = 0.0000000838 * (1 << 11)
            record['longitude'] = high_data * lsb * (-1 if sign else 1)

    def parse_packet_raw(self, payload: bytes, port: int, timestamp: float) -> Optional[Dict[str, Any]]:
        """原始解析模式 - 输出每个ARINC 429字的详细信息，用于调试"""
        if self.supported_ports and port not in self.supported_ports:
            return None

        record = {
            'timestamp': timestamp,
            'packet_size': len(payload),
            'words': []
        }

        offset = 0
        while offset + 4 <= len(payload):
            word = self.decoder.parse_word_from_bytes(payload, offset, 'big')
            offset += 4

            if word == 0:
                continue

            label = self.decoder.extract_label(word)
            label_octal = self.decoder.extract_label_octal(word)
            sdi = self.decoder.extract_sdi(word)
            ssm = self.decoder.extract_ssm(word)

            word_info = {
                'label': label,
                'label_octal': label_octal,
                'sdi': sdi,
                'ssm': ssm,
                'raw_hex': hex(word),
            }
            record['words'].append(word_info)

        return record


@ParserRegistry.register
class RawDataParser(BaseParser):
    """原始数据解析器 - 输出十六进制原始数据"""

    parser_key = "raw_data_parser"
    name = "原始数据解析器"
    supported_ports = []

    def can_parse_port(self, port: int) -> bool:
        return True

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[Dict[str, Any]]:
        return {
            'timestamp': timestamp,
            'raw_data': payload.hex(),
            'packet_size': len(payload),
        }

    def get_output_columns(self, port: int) -> List[str]:
        return ['timestamp', 'raw_data', 'packet_size']
