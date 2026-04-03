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
- 动态端口，从TSN网络配置读取
- 解析时通过包头验证数据格式
"""
import struct
from typing import Dict, List, Any, Optional
from .base import BaseParser, ParserRegistry, FieldLayout


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
    supported_ports = []
    
    DEVICE_ID_MAP = {
        0b00: "航天时代(惯导3)",
        0b01: "陕西华燕(惯导1)",
        0b10: "中科导控(惯导2)",
    }
    
    OUTPUT_COLUMNS = [
        'timestamp',
        'device_id',
        'device_name',
        'heading',
        'pitch',
        'roll',
        'east_velocity',
        'north_velocity',
        'vertical_velocity',
        'latitude',
        'longitude',
        'altitude',
        'angular_rate_x',
        'angular_rate_y',
        'angular_rate_z',
        'accel_x',
        'accel_y',
        'accel_z',
        'work_mode',
        'nav_mode',
        'equip_align_done',
        'sat_source',
        'align_status',
        'align_mode',
        'align_pos_source',
        'fault_status',
        'data_validity',
        'rtk1_hpl',
        'rtk2_hpl',
        'rtk1_vpl',
        'rtk2_vpl',
        'rtk1_sat_count',
        'rtk2_sat_count',
        'rtk1_fix_type',
        'rtk2_fix_type',
        'rtk1_pos_valid',
        'rtk2_pos_valid',
        'sw_version',
        'hw_version',
        'frame_count',
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
    
    def _parse_payload(self, payload: bytes, timestamp: float) -> Dict[str, Any]:
        """解析数据包内容"""
        record = {
            'timestamp': timestamp,
        }
        
        # Byte 3: 设备ID (D0-D1位)
        device_id_byte = payload[3]
        device_id = device_id_byte & 0x03
        record['device_id'] = device_id
        record['device_name'] = self.DEVICE_ID_MAP.get(device_id, f"未知({device_id})")
        
        # Byte 5: 帧计数
        record['frame_count'] = payload[5]
        
        # Byte 6-7: 航向 (unsigned short, LSB=0.01°, 范围0-360°)
        heading_raw = struct.unpack('<H', payload[6:8])[0]
        record['heading'] = heading_raw * 0.01
        
        # Byte 8-9: 俯仰 (signed short, LSB=0.01°, 范围-90~90°)
        pitch_raw = struct.unpack('<h', payload[8:10])[0]
        record['pitch'] = pitch_raw * 0.01
        
        # Byte 10-11: 滚动 (signed short, LSB=0.01°, 范围-180~180°)
        roll_raw = struct.unpack('<h', payload[10:12])[0]
        record['roll'] = roll_raw * 0.01
        
        # Byte 12-13: 东速 (signed short, LSB=0.01 m/s)
        east_vel_raw = struct.unpack('<h', payload[12:14])[0]
        record['east_velocity'] = east_vel_raw * 0.01
        
        # Byte 14-15: 北速 (signed short, LSB=0.01 m/s)
        north_vel_raw = struct.unpack('<h', payload[14:16])[0]
        record['north_velocity'] = north_vel_raw * 0.01
        
        # Byte 16-17: 天速/垂直速度 (signed short, LSB=0.01 m/s)
        vert_vel_raw = struct.unpack('<h', payload[16:18])[0]
        record['vertical_velocity'] = vert_vel_raw * 0.01
        
        # Byte 18-21: 纬度 (signed int, LSB=0.0000001°)
        lat_raw = struct.unpack('<i', payload[18:22])[0]
        record['latitude'] = lat_raw * 0.0000001
        
        # Byte 22-25: 经度 (signed int, LSB=0.0000001°)
        lon_raw = struct.unpack('<i', payload[22:26])[0]
        record['longitude'] = lon_raw * 0.0000001
        
        # Byte 26-29: 高度 (signed int, LSB=0.01m)
        alt_raw = struct.unpack('<i', payload[26:30])[0]
        record['altitude'] = alt_raw * 0.01
        
        # Byte 30-31: X轴角速度 (signed short, LSB=0.01°/s)
        angular_x_raw = struct.unpack('<h', payload[30:32])[0]
        record['angular_rate_x'] = angular_x_raw * 0.01
        
        # Byte 32-33: Y轴角速度 (signed short, LSB=0.01°/s)
        angular_y_raw = struct.unpack('<h', payload[32:34])[0]
        record['angular_rate_y'] = angular_y_raw * 0.01
        
        # Byte 34-35: Z轴角速度 (signed short, LSB=0.01°/s)
        angular_z_raw = struct.unpack('<h', payload[34:36])[0]
        record['angular_rate_z'] = angular_z_raw * 0.01
        
        # Byte 36-37: X轴加速度 (signed short, LSB=0.01 m/s²)
        accel_x_raw = struct.unpack('<h', payload[36:38])[0]
        record['accel_x'] = accel_x_raw * 0.01
        
        # Byte 38-39: Y轴加速度 (signed short, LSB=0.01 m/s²)
        accel_y_raw = struct.unpack('<h', payload[38:40])[0]
        record['accel_y'] = accel_y_raw * 0.01
        
        # Byte 40-41: Z轴加速度 (signed short, LSB=0.01 m/s²)
        accel_z_raw = struct.unpack('<h', payload[40:42])[0]
        record['accel_z'] = accel_z_raw * 0.01
        
        # Byte 42: 工作状态字1 低字节
        byte42 = payload[42]
        record['work_mode'] = self._decode_work_mode(byte42)
        record['nav_mode'] = self._decode_nav_mode(byte42)
        record['equip_align_done'] = "补偿成功" if (byte42 >> 5) & 1 else "未补偿"
        sat_src = (byte42 >> 6) & 0x03
        record['sat_source'] = {0: "N/A", 1: "卫星源1", 2: "卫星源2"}.get(sat_src, f"未知({sat_src})")

        # Byte 43: 工作状态字1 高字节
        byte43 = payload[43]
        record['align_status'] = self._decode_align_status(byte43)
        record['align_mode'] = "动基座对准" if (byte43 >> 2) & 1 else "静基座对准"
        align_pos = (byte43 >> 3) & 0x03
        record['align_pos_source'] = {0: "无位置数据", 1: "卫星导航接收机数据", 2: "飞管经纬高数据"}.get(align_pos, f"未知({align_pos})")

        # Byte 44-45: 故障字1和故障字2
        fault1 = payload[44]
        fault2 = payload[45]
        record['fault_status'] = self._decode_fault_status(fault1, fault2)

        # Byte 46-47: 故障字3（数据有效性）
        record['data_validity'] = self._decode_data_validity(payload[46], payload[47])

        # Byte 48-63: 转换器输出数据 - RTK定位精度
        # 协议: int(4字节), 但有效数据在 D0-D15(低16位), BNR无符号, LSB=0.03125, 高位全零
        record['rtk1_hpl'] = struct.unpack('<H', payload[48:50])[0] * 0.03125
        record['rtk2_hpl'] = struct.unpack('<H', payload[52:54])[0] * 0.03125
        record['rtk1_vpl'] = struct.unpack('<H', payload[56:58])[0] * 0.03125
        record['rtk2_vpl'] = struct.unpack('<H', payload[60:62])[0] * 0.03125

        # Byte 64-65: 天线定位星数 (BNR无符号, D0-D4, 其余位置0)
        record['rtk1_sat_count'] = payload[64] & 0x1F
        record['rtk2_sat_count'] = payload[65] & 0x1F

        # Byte 66-69: 解算信息
        rtk1_fix = struct.unpack('<H', payload[66:68])[0] & 0x1F
        record['rtk1_fix_type'] = self._decode_rtk_fix_type(rtk1_fix)
        rtk2_fix = struct.unpack('<H', payload[68:70])[0] & 0x1F
        record['rtk2_fix_type'] = self._decode_rtk_fix_type(rtk2_fix)

        # Byte 70-71: 定位有效字
        record['rtk1_pos_valid'] = self._decode_rtk_validity(payload[70])
        record['rtk2_pos_valid'] = self._decode_rtk_validity(payload[71])

        # Byte 72-73: 软件版本
        sw_raw = struct.unpack('<H', payload[72:74])[0]
        record['sw_version'] = self._decode_irs_version(sw_raw)

        # Byte 74-75: 硬件版本
        hw_raw = struct.unpack('<H', payload[74:76])[0]
        record['hw_version'] = self._decode_irs_version(hw_raw)

        # Byte 78-79: CRC校验 (从字节2-77计算, 16位)
        crc_received = struct.unpack('<H', payload[78:80])[0]
        crc_computed = self._compute_crc16(payload[2:78])
        record['crc_valid'] = "通过" if crc_received == crc_computed else f"失败(收={crc_received:#06x},算={crc_computed:#06x})"

        return record
    
    def _decode_work_mode(self, byte42: int) -> str:
        """解码工作方式 (Byte 42: D0-D1)"""
        mode = byte42 & 0x03
        mode_map = {
            0: "准备",
            1: "对准",
            2: "导航",
        }
        return mode_map.get(mode, f"未知({mode})")
    
    def _decode_nav_mode(self, byte42: int) -> str:
        """解码导航模式 (Byte 42: D3-D4)"""
        mode = (byte42 >> 3) & 0x03
        mode_map = {
            0: "无导航",
            1: "纯惯性",
            2: "组合导航",
        }
        return mode_map.get(mode, f"未知({mode})")
    
    def _decode_align_status(self, byte43: int) -> str:
        """解码对准状态 (Byte 43: D0-D1)"""
        status = byte43 & 0x03
        status_map = {
            0: "未对准",
            1: "对准进行中",
            2: "对准失败",
            3: "对准成功",
        }
        return status_map.get(status, f"未知({status})")
    
    def _decode_fault_status(self, fault1: int, fault2: int) -> str:
        """解码故障状态"""
        faults = []
        
        # 故障字1
        if fault1 & 0x01:
            faults.append("周期自检故障")
        if fault1 & 0x02:
            faults.append("开机初始化故障")
        
        # 故障字2
        if fault2 & 0x01:
            faults.append("X陀螺故障")
        if fault2 & 0x02:
            faults.append("Y陀螺故障")
        if fault2 & 0x04:
            faults.append("Z陀螺故障")
        if fault2 & 0x08:
            faults.append("X加表故障")
        if fault2 & 0x10:
            faults.append("Y加表故障")
        if fault2 & 0x20:
            faults.append("Z加表故障")
        
        if faults:
            return ",".join(faults)
        return "正常"

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

    @staticmethod
    def _decode_data_validity(byte46: int, byte47: int) -> str:
        """解码故障字3 - 数据有效性 (Byte 46-47)
        byte46 = 协议47B(低字节), byte47 = 协议48B(高字节)
        """
        fields = [
            (byte46, 0, "姿态"), (byte46, 1, "航向角"),
            (byte46, 2, "经纬度"), (byte46, 3, "高度"),
            (byte46, 4, "升降速度"), (byte46, 5, "东向速度"),
            (byte46, 6, "北向速度"), (byte46, 7, "X轴角速度"),
            (byte47, 0, "Y轴角速度"), (byte47, 1, "Z轴角速度"),
            (byte47, 2, "X轴加速度"), (byte47, 3, "Y轴加速度"),
            (byte47, 4, "Z轴加速度"),
        ]
        invalid = [name for b, bit, name in fields if (b >> bit) & 1]
        if invalid:
            return ",".join(invalid) + " 故障"
        return "全部有效"

    @staticmethod
    def _decode_rtk_fix_type(val: int) -> str:
        """解码RTK解算类型"""
        fix_map = {
            0x04: "无效解", 0x08: "单点定位",
            0x0C: "伪距差分", 0x15: "固定解", 0x0D: "浮点解",
        }
        return fix_map.get(val, f"其他({val:#x})")

    @staticmethod
    def _decode_rtk_validity(byte_val: int) -> str:
        """解码RTK卫导有效字
        协议: 卫导信息状态 D0(LSB)-D1(MSB): 01=无效, 11=有效
               DOP值信息状态 D2(LSB)-D3(MSB): 01=无效, 11=有效
        """
        pos_status = byte_val & 0x03
        dop_status = (byte_val >> 2) & 0x03
        pos_str = "有效" if pos_status == 0x03 else ("无效" if pos_status == 0x01 else f"未知({pos_status})")
        dop_str = "有效" if dop_status == 0x03 else ("无效" if dop_status == 0x01 else f"未知({dop_status})")
        return f"定位{pos_str},DOP{dop_str}"

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
