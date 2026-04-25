# -*- coding: utf-8 -*-
"""
IRS 惯性基准系统解析器

根据《惯导通讯协议输出-V3.0》实现
数据包结构：80字节，小端序，包头0xEB 0x90

支持拼包解析：
RS422 网络包结构为 12字节头 + 数据区(长度由 byte[11] 指定)。
IRS 80字节帧可能跨越多个网络包，需要将有效数据拼接后
在字节流中搜索 0xEB 0x90 包头提取完整帧并校验 CRC。

支持的数据字段（与《惯导通讯协议输出-V3.0》字段量纲一致）：
- 姿态角: heading/pitch/roll，单位度 (°)；航向 0–360°，俯仰 ±90°，滚转 ±180°
- 速度: east_velocity / north_velocity / vertical_velocity，单位米每秒 (m/s)
- 位置: latitude / longitude 单位度 (°)；altitude 单位米 (m)，解析为 LSB=0.01m
- 角速度: X/Y/Z轴 (°/s)
- 加速度: X/Y/Z轴 (m/s²)
- 状态: 工作状态字, 故障字, 设备ID

端口配置：
- 动态端口，从 TSN 网络协议读取
- 解析时通过包头验证数据格式
"""
import struct
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout

_BEIJING_TZ = timezone(timedelta(hours=8))


HEADER_BYTE1 = 0xEB
HEADER_BYTE2 = 0x90
PACKET_LENGTH = 80
TSN_TOTAL_LEN = 92
TSN_HEADER_LEN = 12          # 协议填充(4) + 有效位标识(4) + 数据长度(4)
TSN_DATA_AREA_LEN = 80       # 固定80字节数据区(有效数据+零填充)
TSN_VALID_FLAG_OFFSET = 4    # 有效位标识起始偏移
TSN_DATA_LEN_OFFSET = 8      # 数据长度字段起始偏移(大端4字节)


@ParserRegistry.register
class IRSParser(BaseParser):
    """IRS惯性基准系统解析器（支持拼包）"""
    
    parser_key = "irs_v3"
    name = "IRS惯性基准系统"
    display_name = "IRS 惯性基准系统"
    parser_version = "V3"
    protocol_family = "irs"
    supported_ports = []
    
    DEVICE_ID_MAP = {
        0b00: "航天时代(惯导3)",
        0b01: "陕西华燕(惯导1)",
        0b10: "中科导控(惯导2)",
    }
    
    OUTPUT_COLUMNS = [
        'timestamp',
        'BeijingDateTime',
        'device_id', 'device_name_enum',
        'frame_count',
        'heading', 'pitch', 'roll',
        'east_velocity', 'north_velocity', 'vertical_velocity',
        'latitude', 'longitude', 'altitude',
        'angular_rate_x', 'angular_rate_y', 'angular_rate_z',
        'accel_x', 'accel_y', 'accel_z',
        # 枚举状态（原始值 + _enum 含义）
        'work_mode', 'work_mode_enum',
        'nav_mode', 'nav_mode_enum',
        'p_align_status', 'p_align_status_enum',
        'sat_source', 'sat_source_enum',
        'align_status', 'align_status_enum',
        'align_mode', 'align_mode_enum',
        'align_pos_source', 'align_pos_source_enum',
        # 故障状态（每个子项独立列，0=正常 1=故障）
        'cycle_self_check_status', 'cycle_self_check_status_enum',
        'poweron_self_check_status', 'poweron_self_check_status_enum',
        'x_gyro_status', 'x_gyro_status_enum',
        'y_gyro_status', 'y_gyro_status_enum',
        'z_gyro_status', 'z_gyro_status_enum',
        'x_accelerometer_status', 'x_accelerometer_status_enum',
        'y_accelerometer_status', 'y_accelerometer_status_enum',
        'z_accelerometer_status', 'z_accelerometer_status_enum',
        # 数据有效性（协议原始bit：0=正常 1=故障）
        'attitude_status', 'attitude_status_enum',
        'heading_status', 'heading_status_enum',
        'position_status', 'position_status_enum',
        'altitude_status', 'altitude_status_enum',
        'velocity_ud_status', 'velocity_ud_status_enum',
        'velocity_ew_status', 'velocity_ew_status_enum',
        'velocity_ns_status', 'velocity_ns_status_enum',
        'x_axis_angular_velocity_status', 'x_axis_angular_velocity_status_enum',
        'y_axis_angular_velocity_status', 'y_axis_angular_velocity_status_enum',
        'z_axis_angular_velocity_status', 'z_axis_angular_velocity_status_enum',
        'x_axis_acceleration_status', 'x_axis_acceleration_status_enum',
        'y_axis_acceleration_status', 'y_axis_acceleration_status_enum',
        'z_axis_acceleration_status', 'z_axis_acceleration_status_enum',
        # RTK
        'rtk1_hpl', 'rtk2_hpl', 'rtk1_vpl', 'rtk2_vpl',
        'rtk1_sat_count', 'rtk2_sat_count',
        'rtk1_fix_type', 'rtk1_fix_type_enum',
        'rtk2_fix_type', 'rtk2_fix_type_enum',
        'rtk1_pos_valid', 'rtk1_pos_valid_enum',
        'rtk1_dop_valid', 'rtk1_dop_valid_enum',
        'rtk2_pos_valid', 'rtk2_pos_valid_enum',
        'rtk2_dop_valid', 'rtk2_dop_valid_enum',
        # 版本
        'sw_version', 'hw_version',
        'crc_valid',
    ]
    
    def __init__(self):
        self._port_buffers: Dict[int, bytearray] = {}
        self._port_timestamps: Dict[int, float] = {}
        self._port_skip: Dict[int, int] = {}
    
    def reset_buffers(self):
        """清空所有端口的拼包缓冲区"""
        self._port_buffers.clear()
        self._port_timestamps.clear()
        self._port_skip.clear()
    
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
        喂入一个 TSN 网络包，返回从拼包缓冲区中提取出的所有完整 IRS 帧解析结果。
        
        TSN 网络包固定 92 字节:
          [0-3]   协议填充 (4字节)
          [4-7]   有效位标识 (4字节, 0x03000000 = 有效)
          [8-11]  数据长度 (大端4字节, 值范围 0~80)
          [12-91] 数据区 (固定80字节, 前 data_len 字节有效, 其余填0)
        
        只提取有效数据追加到端口缓冲区，然后扫描缓冲区提取完整的 80 字节 IRS 帧。
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
            self._port_skip[port] = 0
        
        self._port_buffers[port].extend(effective_data)
        self._port_timestamps[port] = timestamp
        
        results.extend(self._drain_buffer(port))
        return results
    
    def _drain_buffer(self, port: int) -> List[Dict[str, Any]]:
        """从缓冲区中尽可能多地提取完整 IRS 帧。
        
        用逻辑偏移 skip 避免反复 del buf[:1] 的 O(n²) 拷贝，
        达到阈值后一次性压缩。
        """
        results = []
        buf = self._port_buffers[port]
        ts = self._port_timestamps[port]
        skip = self._port_skip.setdefault(port, 0)
        COMPACT_THRESHOLD = 4096

        while True:
            if skip >= COMPACT_THRESHOLD:
                del buf[:skip]
                skip = 0

            remaining = len(buf) - skip
            if remaining < PACKET_LENGTH:
                break

            idx = self._find_header_from(buf, skip)

            if idx < 0:
                if len(buf) > skip and buf[-1] == HEADER_BYTE1:
                    keep_from = len(buf) - 1
                    del buf[:keep_from]
                else:
                    buf.clear()
                skip = 0
                break

            if idx > skip:
                skip = idx
                continue

            frame = bytes(buf[skip:skip + PACKET_LENGTH])
            if frame[4] != PACKET_LENGTH:
                skip += 1
                continue

            crc_received = struct.unpack('<H', frame[78:80])[0]
            crc_computed = self._compute_crc16(frame[2:78])
            if crc_received != crc_computed:
                skip += 1
                continue

            skip += PACKET_LENGTH
            try:
                record = self._parse_payload(frame, ts)
                results.append(record)
            except Exception:
                pass

        if skip > 0:
            del buf[:skip]
            skip = 0
        self._port_skip[port] = skip
        return results

    @staticmethod
    def _find_header_from(buf: bytearray, start: int) -> int:
        """在 buf 中从 start 位置搜索 0xEB 0x90，返回绝对索引或 -1"""
        pos = start
        n = len(buf)
        while pos <= n - 2:
            idx = buf.find(HEADER_BYTE1, pos)
            if idx < 0 or idx + 1 >= n:
                return -1
            if buf[idx + 1] == HEADER_BYTE2:
                return idx
            pos = idx + 1
        return -1
    
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
        """
        兼容接口：单包解析（不使用拼包）。
        对于需要拼包的场景，请使用 feed_packet + flush_buffer。
        """
        irs_data = self._extract_irs_data(payload, field_layout)
        if irs_data is None:
            return None
        try:
            return self._parse_payload(irs_data, timestamp)
        except Exception:
            return None
    
    def _extract_irs_data(
        self,
        payload: bytes,
        field_layout: Optional[List[FieldLayout]] = None
    ) -> Optional[bytes]:
        """从 payload 中提取 IRS 数据帧（仅用于单包解析兼容模式）"""
        if field_layout:
            for field in field_layout:
                if field.field_name == '422数据包':
                    offset = field.field_offset
                    if offset + PACKET_LENGTH <= len(payload):
                        candidate = payload[offset:offset + PACKET_LENGTH]
                        if candidate[0] == HEADER_BYTE1 and candidate[1] == HEADER_BYTE2:
                            return candidate
        
        if len(payload) >= PACKET_LENGTH:
            if payload[0] == HEADER_BYTE1 and payload[1] == HEADER_BYTE2:
                if payload[4] == PACKET_LENGTH:
                    return payload[:PACKET_LENGTH]
        
        if len(payload) >= TSN_HEADER_LEN + PACKET_LENGTH:
            candidate = payload[TSN_HEADER_LEN:TSN_HEADER_LEN + PACKET_LENGTH]
            if candidate[0] == HEADER_BYTE1 and candidate[1] == HEADER_BYTE2:
                if candidate[4] == PACKET_LENGTH:
                    return candidate
        
        return None
    
    # ---- 枚举映射表 ----
    _WORK_MODE_MAP = {0: "准备", 1: "对准", 2: "导航"}
    _NAV_MODE_MAP = {0: "无导航", 1: "纯惯性", 2: "组合导航"}
    _P_ALIGN_MAP = {0: "未补偿", 1: "补偿成功"}
    _SAT_SOURCE_MAP = {0: "卫星源1", 1: "卫星源2"}
    _ALIGN_STATUS_MAP = {0: "未对准", 1: "对准进行中", 2: "对准失败", 3: "对准成功"}
    _ALIGN_MODE_MAP = {0: "静基座对准", 1: "动基座对准"}
    _ALIGN_POS_SRC_MAP = {0: "无位置数据", 1: "卫星导航接收机数据", 2: "飞管经纬高数据"}
    _FAULT_ENUM = {0: "正常", 1: "故障"}
    _VALID_ENUM = {0: "正常", 1: "故障"}

    def _parse_payload(self, payload: bytes, timestamp: float) -> Dict[str, Any]:
        """解析数据包内容"""
        record: Dict[str, Any] = {'timestamp': timestamp}

        # BeijingDateTime
        try:
            dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            dt_bj = dt_utc.astimezone(_BEIJING_TZ)
            record['BeijingDateTime'] = dt_bj.strftime('%Y-%m-%d %H:%M:%S.') + f"{dt_bj.microsecond // 1000:03d}"
        except Exception:
            record['BeijingDateTime'] = ''

        # Byte 3: 设备ID (D0-D1)
        device_id = payload[3] & 0x03
        record['device_id'] = device_id
        record['device_name_enum'] = self.DEVICE_ID_MAP.get(device_id, f"未知({device_id})")

        # Byte 5: 帧计数
        record['frame_count'] = payload[5]

        # Byte 6-7: 航向
        record['heading'] = struct.unpack('<H', payload[6:8])[0] * 0.01
        # Byte 8-9: 俯仰
        record['pitch'] = struct.unpack('<h', payload[8:10])[0] * 0.01
        # Byte 10-11: 滚动
        record['roll'] = struct.unpack('<h', payload[10:12])[0] * 0.01
        # Byte 12-13: 东速
        record['east_velocity'] = struct.unpack('<h', payload[12:14])[0] * 0.01
        # Byte 14-15: 北速
        record['north_velocity'] = struct.unpack('<h', payload[14:16])[0] * 0.01
        # Byte 16-17: 天速
        record['vertical_velocity'] = struct.unpack('<h', payload[16:18])[0] * 0.01
        # Byte 18-21: 纬度
        record['latitude'] = struct.unpack('<i', payload[18:22])[0] * 0.0000001
        # Byte 22-25: 经度
        record['longitude'] = struct.unpack('<i', payload[22:26])[0] * 0.0000001
        # Byte 26-29: 高度
        record['altitude'] = struct.unpack('<i', payload[26:30])[0] * 0.01
        # Byte 30-35: 角速度 X/Y/Z
        record['angular_rate_x'] = struct.unpack('<h', payload[30:32])[0] * 0.01
        record['angular_rate_y'] = struct.unpack('<h', payload[32:34])[0] * 0.01
        record['angular_rate_z'] = struct.unpack('<h', payload[34:36])[0] * 0.01
        # Byte 36-41: 加速度 X/Y/Z
        record['accel_x'] = struct.unpack('<h', payload[36:38])[0] * 0.01
        record['accel_y'] = struct.unpack('<h', payload[38:40])[0] * 0.01
        record['accel_z'] = struct.unpack('<h', payload[40:42])[0] * 0.01

        # ---- Byte 42: 工作状态字1 低字节 ----
        byte42 = payload[42]
        wm = byte42 & 0x03
        record['work_mode'] = wm
        record['work_mode_enum'] = self._WORK_MODE_MAP.get(wm, f"未知({wm})")

        nm = (byte42 >> 3) & 0x03
        record['nav_mode'] = nm
        record['nav_mode_enum'] = self._NAV_MODE_MAP.get(nm, f"未知({nm})")

        pa_val = (byte42 >> 5) & 0x01
        record['p_align_status'] = pa_val
        record['p_align_status_enum'] = self._P_ALIGN_MAP.get(pa_val, f"未知({pa_val})")

        ss = (byte42 >> 6) & 0x01
        record['sat_source'] = ss
        record['sat_source_enum'] = self._SAT_SOURCE_MAP.get(ss, f"未知({ss})")

        # ---- Byte 43: 工作状态字1 高字节 ----
        byte43 = payload[43]
        als = byte43 & 0x03
        record['align_status'] = als
        record['align_status_enum'] = self._ALIGN_STATUS_MAP.get(als, f"未知({als})")

        alm = (byte43 >> 2) & 0x01
        record['align_mode'] = alm
        record['align_mode_enum'] = self._ALIGN_MODE_MAP.get(alm, f"未知({alm})")

        aps = (byte43 >> 3) & 0x03
        record['align_pos_source'] = aps
        record['align_pos_source_enum'] = self._ALIGN_POS_SRC_MAP.get(aps, f"未知({aps})")

        # ---- Byte 44-45: 故障字1 & 故障字2（每个子状态独立列，0=正常 1=故障）----
        fault1 = payload[44]
        fault2 = payload[45]
        self._decode_fault_fields(record, fault1, fault2)

        # ---- Byte 46-47: 数据有效性（协议bit取反：0→1=有效，1→0=无效）----
        self._decode_validity_fields(record, payload[46], payload[47])

        # ---- RTK 精度 ----
        record['rtk1_hpl'] = struct.unpack('<H', payload[48:50])[0] * 0.03125
        record['rtk2_hpl'] = struct.unpack('<H', payload[52:54])[0] * 0.03125
        record['rtk1_vpl'] = struct.unpack('<H', payload[56:58])[0] * 0.03125
        record['rtk2_vpl'] = struct.unpack('<H', payload[60:62])[0] * 0.03125

        record['rtk1_sat_count'] = payload[64] & 0x1F
        record['rtk2_sat_count'] = payload[65] & 0x1F

        rtk1_fix = struct.unpack('<H', payload[66:68])[0] & 0x1F
        record['rtk1_fix_type'] = rtk1_fix
        record['rtk1_fix_type_enum'] = self._decode_rtk_fix_type(rtk1_fix)
        rtk2_fix = struct.unpack('<H', payload[68:70])[0] & 0x1F
        record['rtk2_fix_type'] = rtk2_fix
        record['rtk2_fix_type_enum'] = self._decode_rtk_fix_type(rtk2_fix)

        self._decode_rtk_validity_fields(record, 'rtk1', payload[70])
        self._decode_rtk_validity_fields(record, 'rtk2', payload[71])

        # 版本
        record['sw_version'] = self._decode_irs_version(struct.unpack('<H', payload[72:74])[0])
        record['hw_version'] = self._decode_irs_version(struct.unpack('<H', payload[74:76])[0])

        # CRC
        crc_received = struct.unpack('<H', payload[78:80])[0]
        crc_computed = self._compute_crc16(payload[2:78])
        record['crc_valid'] = "通过" if crc_received == crc_computed else f"失败(收={crc_received:#06x},算={crc_computed:#06x})"

        return record
    
    def _decode_fault_fields(self, record: Dict[str, Any], fault1: int, fault2: int) -> None:
        """将故障字1/2拆分为独立列（原始值 0=正常 1=故障 + _enum 含义）"""
        fe = self._FAULT_ENUM
        # 故障字1
        v = fault1 & 0x01
        record['cycle_self_check_status'] = v
        record['cycle_self_check_status_enum'] = fe[v]
        v = (fault1 >> 1) & 0x01
        record['poweron_self_check_status'] = v
        record['poweron_self_check_status_enum'] = fe[v]
        # 故障字2
        v = fault2 & 0x01
        record['x_gyro_status'] = v
        record['x_gyro_status_enum'] = fe[v]
        v = (fault2 >> 1) & 0x01
        record['y_gyro_status'] = v
        record['y_gyro_status_enum'] = fe[v]
        v = (fault2 >> 2) & 0x01
        record['z_gyro_status'] = v
        record['z_gyro_status_enum'] = fe[v]
        v = (fault2 >> 3) & 0x01
        record['x_accelerometer_status'] = v
        record['x_accelerometer_status_enum'] = fe[v]
        v = (fault2 >> 4) & 0x01
        record['y_accelerometer_status'] = v
        record['y_accelerometer_status_enum'] = fe[v]
        v = (fault2 >> 5) & 0x01
        record['z_accelerometer_status'] = v
        record['z_accelerometer_status_enum'] = fe[v]

    @staticmethod
    def _compute_crc16(data: bytes) -> int:
        """CRC-16/XMODEM 校验计算 (Byte 2-77, 多项式0x1021, 初始值0x0000)"""
        crc = 0x0000
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021
                else:
                    crc <<= 1
                crc &= 0xFFFF
        return crc

    def _decode_validity_fields(self, record: Dict[str, Any], byte46: int, byte47: int) -> None:
        """将数据有效性拆分为独立列。

        直接输出协议原始 bit：0=正常，1=故障。
        """
        ve = self._VALID_ENUM
        fields = [
            (byte46, 0, 'attitude_status'),
            (byte46, 1, 'heading_status'),
            (byte46, 2, 'position_status'),
            (byte46, 3, 'altitude_status'),
            (byte46, 4, 'velocity_ud_status'),
            (byte46, 5, 'velocity_ew_status'),
            (byte46, 6, 'velocity_ns_status'),
            (byte46, 7, 'x_axis_angular_velocity_status'),
            (byte47, 0, 'y_axis_angular_velocity_status'),
            (byte47, 1, 'z_axis_angular_velocity_status'),
            (byte47, 2, 'x_axis_acceleration_status'),
            (byte47, 3, 'y_axis_acceleration_status'),
            (byte47, 4, 'z_axis_acceleration_status'),
        ]
        for b, bit, col in fields:
            v = (b >> bit) & 0x01
            record[col] = v
            record[col + '_enum'] = ve[v]

    @staticmethod
    def _decode_rtk_fix_type(val: int) -> str:
        """解码RTK解算类型"""
        fix_map = {
            0x04: "无效解", 0x08: "单点定位",
            0x0C: "伪距差分", 0x15: "固定解", 0x0D: "浮点解",
        }
        return fix_map.get(val, f"其他({val:#x})")

    _RTK_VALID_MAP = {0x03: "有效", 0x01: "无效"}

    @staticmethod
    def _decode_rtk_validity_fields(record: Dict[str, Any], prefix: str, byte_val: int) -> None:
        """拆分 RTK 卫导有效字为独立列（原始值 + _enum）。
        D0-D1: 定位有效性 (01=无效, 11=有效)
        D2-D3: DOP有效性  (01=无效, 11=有效)
        """
        vm = IRSParser._RTK_VALID_MAP
        pos = byte_val & 0x03
        dop = (byte_val >> 2) & 0x03
        record[f'{prefix}_pos_valid'] = pos
        record[f'{prefix}_pos_valid_enum'] = vm.get(pos, f"未知({pos})")
        record[f'{prefix}_dop_valid'] = dop
        record[f'{prefix}_dop_valid_enum'] = vm.get(dop, f"未知({dop})")

    @staticmethod
    def _decode_irs_version(raw16: int) -> str:
        """解码惯导软件/硬件版本号
        D0-D5: 小版本号(0-63), D6-D9: 大版本号(0-15), D10-D11: 厂家编号
        输出格式: 厂家X-V大版本.0小版本
        """
        minor = raw16 & 0x3F
        major = (raw16 >> 6) & 0x0F
        vendor_id = (raw16 >> 10) & 0x03
        vendor_map = {0: "航天时代", 1: "陕西华燕", 2: "中科导控"}
        vendor = vendor_map.get(vendor_id, f"厂家{vendor_id}")
        return f"{vendor}-V{major}.{minor:03d}"

    def get_output_columns(self, port: int) -> List[str]:
        """获取输出列名"""
        return self.OUTPUT_COLUMNS
