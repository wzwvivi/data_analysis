# -*- coding: utf-8 -*-
"""
ARINC 429 通用解码模块

ARINC 429 是航空电子设备间通信的标准协议。
每个字(word)为32位，结构如下：
- Bit 1-8: Label (标号，八进制表示)
- Bit 9-10: SDI (Source/Destination Identifier)
- Bit 11-29: Data (数据位，具体含义取决于数据类型)
- Bit 30-31: SSM (Sign/Status Matrix)
- Bit 32: Parity (奇校验位)

数据类型：
- BNR (Binary): 二进制数值
- BCD (Binary Coded Decimal): BCD编码
- Discrete: 离散量
"""
from typing import Dict, Any, Optional, Tuple
import struct


class ARINC429Decoder:
    """ARINC 429 字解码器"""
    
    @staticmethod
    def extract_label(word: int) -> int:
        """
        提取标号 (Bit 1-8)
        注意：ARINC 429 标号是按位反转的八进制数
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            标号值（八进制表示的十进制值）
        """
        label_bits = word & 0xFF
        # 位反转
        reversed_label = 0
        for i in range(8):
            if label_bits & (1 << i):
                reversed_label |= (1 << (7 - i))
        return reversed_label
    
    @staticmethod
    def extract_label_octal(word: int) -> str:
        """
        提取标号并返回八进制字符串
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            八进制标号字符串，如 "310"
        """
        label = ARINC429Decoder.extract_label(word)
        return oct(label)[2:].zfill(3)
    
    @staticmethod
    def extract_sdi(word: int) -> int:
        """
        提取SDI (Bit 9-10)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            SDI值 (0-3)
        """
        return (word >> 8) & 0x03
    
    @staticmethod
    def extract_ssm(word: int) -> int:
        """
        提取SSM (Bit 30-31)
        
        SSM含义（对于BNR数据）：
        - 00: 故障告警 (Failure Warning)
        - 01: 非计算数据 (No Computed Data)
        - 10: 功能测试 (Functional Test)
        - 11: 正常工作 (Normal Operation)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            SSM值 (0-3)
        """
        return (word >> 29) & 0x03
    
    @staticmethod
    def extract_sign_bit(word: int) -> int:
        """
        提取符号位 (Bit 29)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            符号位 (0=正, 1=负)
        """
        return (word >> 28) & 0x01
    
    @staticmethod
    def extract_data_bits(word: int, start_bit: int, end_bit: int) -> int:
        """
        提取指定范围的数据位
        
        Args:
            word: 32位ARINC 429字
            start_bit: 起始位（1-32，包含）
            end_bit: 结束位（1-32，包含）
            
        Returns:
            提取的数据值
        """
        # 转换为0索引
        start = start_bit - 1
        end = end_bit - 1
        mask = ((1 << (end - start + 1)) - 1) << start
        return (word & mask) >> start
    
    @staticmethod
    def decode_bnr(word: int, msb_bit: int, lsb_bit: int, 
                   scale: float, signed: bool = True) -> float:
        """
        解码BNR (Binary) 数据
        
        Args:
            word: 32位ARINC 429字
            msb_bit: 最高有效位位置 (1-32)
            lsb_bit: 最低有效位位置 (1-32)
            scale: 缩放系数 (通常是满量程值)
            signed: 是否有符号
            
        Returns:
            解码后的浮点数值
        """
        # 提取数据位
        data = ARINC429Decoder.extract_data_bits(word, lsb_bit, msb_bit)
        num_bits = msb_bit - lsb_bit + 1
        
        if signed:
            # 检查符号位（通常是Bit 29）
            sign = ARINC429Decoder.extract_sign_bit(word)
            if sign:
                # 负数：取补码
                data = -data
        
        # 计算LSB值并缩放
        lsb_value = scale / (2 ** num_bits)
        return data * lsb_value
    
    @staticmethod
    def decode_bnr_with_lsb(word: int, msb_bit: int, lsb_bit: int,
                            lsb_value: float, signed: bool = True) -> float:
        """
        使用LSB值解码BNR数据
        
        Args:
            word: 32位ARINC 429字
            msb_bit: 最高有效位位置
            lsb_bit: 最低有效位位置
            lsb_value: LSB的物理值
            signed: 是否有符号
            
        Returns:
            解码后的浮点数值
        """
        data = ARINC429Decoder.extract_data_bits(word, lsb_bit, msb_bit)
        
        if signed:
            sign = ARINC429Decoder.extract_sign_bit(word)
            if sign:
                data = -data
        
        return data * lsb_value
    
    @staticmethod
    def decode_bcd(word: int, start_bit: int, num_digits: int) -> int:
        """
        解码BCD (Binary Coded Decimal) 数据
        
        Args:
            word: 32位ARINC 429字
            start_bit: 起始位
            num_digits: BCD位数
            
        Returns:
            解码后的整数值
        """
        result = 0
        multiplier = 1
        
        for i in range(num_digits):
            bit_pos = start_bit + i * 4
            digit = ARINC429Decoder.extract_data_bits(word, bit_pos, bit_pos + 3)
            result += digit * multiplier
            multiplier *= 10
        
        return result
    
    @staticmethod
    def decode_beijing_time(word: int) -> Tuple[int, int, int]:
        """
        解码北京时间 (Label 125)
        
        根据协议文件：
        - Bit 9-12: 秒个位 (1秒)
        - Bit 13-15: 秒十位 (10秒)
        - Bit 16-19: 分个位 (1分)
        - Bit 20-22: 分十位 (10分)
        - Bit 23-26: 时个位 (1小时)
        - Bit 27-28: 时十位 (10小时)
        
        Returns:
            (hours, minutes, seconds)
        """
        # 秒
        sec_ones = ARINC429Decoder.extract_data_bits(word, 9, 12)
        sec_tens = ARINC429Decoder.extract_data_bits(word, 13, 15)
        seconds = sec_tens * 10 + sec_ones
        
        # 分
        min_ones = ARINC429Decoder.extract_data_bits(word, 16, 19)
        min_tens = ARINC429Decoder.extract_data_bits(word, 20, 22)
        minutes = min_tens * 10 + min_ones
        
        # 时
        hour_ones = ARINC429Decoder.extract_data_bits(word, 23, 26)
        hour_tens = ARINC429Decoder.extract_data_bits(word, 27, 28)
        hours = hour_tens * 10 + hour_ones
        
        return hours, minutes, seconds
    
    @staticmethod
    def is_valid(word: int) -> bool:
        """
        检查SSM是否表示数据有效
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            True如果SSM=11（正常工作）
        """
        ssm = ARINC429Decoder.extract_ssm(word)
        return ssm == 0x03
    
    @staticmethod
    def parse_word_from_bytes(data: bytes, offset: int = 0, 
                               byte_order: str = 'little') -> int:
        """
        从字节数据中解析ARINC 429字
        
        Args:
            data: 字节数据
            offset: 偏移量
            byte_order: 字节序 ('little' 或 'big')
            
        Returns:
            32位ARINC 429字
        """
        if offset + 4 > len(data):
            return 0
        
        word_bytes = data[offset:offset + 4]
        if byte_order == 'little':
            return struct.unpack('<I', word_bytes)[0]
        else:
            return struct.unpack('>I', word_bytes)[0]
    
    @staticmethod
    def decode_latitude_high(word: int) -> Tuple[int, int]:
        """
        解码纬度高20位 (Label 310)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            (data_bits, sign) - 高20位数据和符号
        """
        # 数据位: Bit 9-28 (20位)
        data = ARINC429Decoder.extract_data_bits(word, 9, 28)
        sign = ARINC429Decoder.extract_sign_bit(word)
        return data, sign
    
    @staticmethod
    def decode_latitude_low(word: int) -> int:
        """
        解码纬度低11位 (Label 313)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            低11位数据
        """
        # 数据位: Bit 9-19 (11位)
        return ARINC429Decoder.extract_data_bits(word, 9, 19)
    
    @staticmethod
    def combine_latitude(high_word: int, low_word: int) -> float:
        """
        合并纬度高低位并计算最终值
        
        根据协议：31位数据的LSB为 0.0000000838
        
        Args:
            high_word: 标号310的字
            low_word: 标号313的字
            
        Returns:
            纬度值（度）
        """
        high_data, sign = ARINC429Decoder.decode_latitude_high(high_word)
        low_data = ARINC429Decoder.decode_latitude_low(low_word)
        
        combined = (high_data << 11) | low_data
        
        latitude = combined * 0.0000000838
        
        if sign:
            latitude = -latitude
        
        return latitude
    
    @staticmethod
    def decode_longitude_high(word: int) -> Tuple[int, int]:
        """
        解码经度高20位 (Label 311)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            (data_bits, sign) - 高20位数据和符号
        """
        data = ARINC429Decoder.extract_data_bits(word, 9, 28)
        sign = ARINC429Decoder.extract_sign_bit(word)
        return data, sign
    
    @staticmethod
    def decode_longitude_low(word: int) -> int:
        """
        解码经度低11位 (Label 317)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            低11位数据
        """
        return ARINC429Decoder.extract_data_bits(word, 9, 19)
    
    @staticmethod
    def combine_longitude(high_word: int, low_word: int) -> float:
        """
        合并经度高低位并计算最终值
        
        根据协议：31位数据的LSB为 0.0000000838（与纬度相同）
        
        Args:
            high_word: 标号311的字
            low_word: 标号317的字
            
        Returns:
            经度值（度）
        """
        high_data, sign = ARINC429Decoder.decode_longitude_high(high_word)
        low_data = ARINC429Decoder.decode_longitude_low(low_word)
        
        combined = (high_data << 11) | low_data
        
        longitude = combined * 0.0000000838
        
        if sign:
            longitude = -longitude
        
        return longitude
    
    @staticmethod
    def decode_ground_speed(word: int) -> float:
        """
        解码地速 (Label 312)
        
        根据协议：
        - 数据范围: 0~8192 km/h
        - 分辨率: 0.0078125 km/h
        - 有效位数: 20位 (Bit 9-28)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            地速值（km/h）
        """
        data = ARINC429Decoder.extract_data_bits(word, 9, 28)
        return data * 0.0078125
    
    @staticmethod
    def decode_true_heading(word: int) -> float:
        """
        解码真航向 (Label 314)
        
        根据协议：
        - 数据范围: 0~360°
        - 分辨率: 0.000171661376953125°
        - 有效位数: 21位 (Bit 9-29)
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            真航向值（度）
        """
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        return data * 0.000171661376953125
    
    @staticmethod
    def decode_track_angle(word: int) -> float:
        """
        解码真航迹角 (Label 322)
        
        根据协议：
        - 数据范围: 0~360°
        - 有效位数: 20位 (Bit 9-28)
        - MSB值: 180°
        
        Args:
            word: 32位ARINC 429字
            
        Returns:
            真航迹角值（度）
        """
        data = ARINC429Decoder.extract_data_bits(word, 9, 28)
        sign = ARINC429Decoder.extract_sign_bit(word)
        
        # LSB = 180 / 2^19
        lsb = 180.0 / (2 ** 19)
        angle = data * lsb
        
        if sign:
            angle = -angle
        
        # 转换为0-360范围
        if angle < 0:
            angle += 360
        
        return angle
    
    @staticmethod
    def _decode_signed_bnr_20bit(word: int, lsb: float) -> float:
        """
        解码20位有符号BNR数据（Bit 29为符号位，Bit 9-28为数据位）
        
        负数采用二补码编码：将符号位+数据位作为21位二补码整体解读。
        """
        raw_21 = ARINC429Decoder.extract_data_bits(word, 9, 29)
        if raw_21 >= (1 << 20):
            raw_21 -= (1 << 21)
        return raw_21 * lsb

    @staticmethod
    def decode_vertical_velocity(word: int) -> float:
        """
        解码天向速度/垂直速度 (Label 365)
        
        Bit 29=符号, Bit 9-28=20位数据, 二补码
        LSB = 0.00048828125, 范围 +-512
        """
        return ARINC429Decoder._decode_signed_bnr_20bit(word, 0.00048828125)
    
    @staticmethod
    def decode_north_velocity(word: int) -> float:
        """
        解码北向速度 (Label 366)
        
        Bit 29=符号, Bit 9-28=20位数据, 二补码
        协议分辨率: 0.0021092063
        """
        return ARINC429Decoder._decode_signed_bnr_20bit(word, 0.0021092063)
    
    @staticmethod
    def decode_east_velocity(word: int) -> float:
        """
        解码东向速度 (Label 367)
        
        Bit 29=符号, Bit 9-28=20位数据, 二补码
        协议分辨率: 0.0021092063
        """
        return ARINC429Decoder._decode_signed_bnr_20bit(word, 0.0021092063)
    
    @staticmethod
    def decode_geometric_height(word: int) -> float:
        """
        解码几何高度 (Label 361)
        分辨率: 0.03125 m, 21位 (Bit 9-29)
        """
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        sign = ARINC429Decoder.extract_sign_bit(word)
        
        height = data * 0.03125
        
        if sign:
            height = -height
        
        return height

    @staticmethod
    def decode_squawk_code(word: int) -> str:
        """
        解码应答代码/识别代码 (Label 031)
        BCD编码, 四位八进制数
        Bit18~20: 个位, Bit21~23: 十位, Bit24~26: 百位, Bit27~29: 千位
        """
        d1 = ARINC429Decoder.extract_data_bits(word, 18, 20)  # 个位
        d2 = ARINC429Decoder.extract_data_bits(word, 21, 23)  # 十位
        d3 = ARINC429Decoder.extract_data_bits(word, 24, 26)  # 百位
        d4 = ARINC429Decoder.extract_data_bits(word, 27, 29)  # 千位
        return f"{d4}{d3}{d2}{d1}"

    @staticmethod
    def decode_work_status_306(word: int) -> dict:
        """
        解码工作状态 (Label 306) - 离散量
        输入方向: 设置工作状态; 输出方向: 工作状态回传
        """
        bits = {}
        bits['fault'] = (word >> 8) & 1                  # Bit9
        bits['self_test'] = (word >> 9) & 3               # Bit10-11
        bits['work_mode'] = (word >> 11) & 3              # Bit12-13
        bits['adsb_out'] = (word >> 13) & 1               # Bit14
        bits['adsb_in'] = (word >> 14) & 1                # Bit15
        bits['air_ground'] = (word >> 15) & 1             # Bit16
        bits['receiver_fault'] = (word >> 16) & 1         # Bit17
        bits['transmitter_fault'] = (word >> 17) & 1      # Bit18
        bits['signal_proc_fault'] = (word >> 18) & 1      # Bit19
        bits['power_fault'] = (word >> 19) & 1            # Bit20
        bits['altitude_invalid'] = (word >> 20) & 1       # Bit21
        bits['nav_invalid'] = (word >> 21) & 1            # Bit22
        bits['lock_normal'] = (word >> 25) & 1            # Bit26
        bits['adsb_broadcasting'] = (word >> 26) & 1      # Bit27
        bits['responding'] = (word >> 27) & 1             # Bit28
        bits['spi'] = (word >> 28) & 1                    # Bit29
        return bits

    @staticmethod
    def decode_smode_address(word1: int, word2: int) -> str:
        """
        解码S模式地址 (Label 331 + 332)
        331: Bit10-29, 5个十六进制位 (低20位)
        332: Bit10-13, 1个十六进制位 (最高4位)
        合计24位 = 6个十六进制字符
        """
        low_20 = ARINC429Decoder.extract_data_bits(word1, 10, 29)
        high_4 = ARINC429Decoder.extract_data_bits(word2, 10, 13)
        full_addr = (high_4 << 20) | low_20
        return f"{full_addr:06X}"

    @staticmethod
    def decode_smode_addr_low(word: int) -> int:
        """解码S模式地址低20位 (Label 331), Bit10-29"""
        return ARINC429Decoder.extract_data_bits(word, 10, 29)

    @staticmethod
    def decode_smode_addr_high(word: int) -> int:
        """解码S模式地址高4位 (Label 332), Bit10-13"""
        return ARINC429Decoder.extract_data_bits(word, 10, 13)

    @staticmethod
    def _decode_flight_char(val: int) -> str:
        """将航班号单个6位字符值转为可读字符"""
        if val == 0x20:
            return ' '
        if 0x01 <= val <= 0x1A:
            return chr(ord('A') + val - 1)
        if 0x30 <= val <= 0x39:
            return chr(ord('0') + val - 0x30)
        return '?'

    @staticmethod
    def decode_flight_id_1(word: int) -> str:
        """
        解码航班号1 (Label 261): 字符1-3
        Bit11-16: 倒数第1位, Bit17-22: 倒数第2位, Bit23-28: 倒数第3位
        """
        c1 = ARINC429Decoder.extract_data_bits(word, 11, 16)
        c2 = ARINC429Decoder.extract_data_bits(word, 17, 22)
        c3 = ARINC429Decoder.extract_data_bits(word, 23, 28)
        return (ARINC429Decoder._decode_flight_char(c3) +
                ARINC429Decoder._decode_flight_char(c2) +
                ARINC429Decoder._decode_flight_char(c1))

    @staticmethod
    def decode_flight_id_2(word: int) -> str:
        """
        解码航班号2 (Label 235): 字符4-6
        Bit11-16: 倒数第4位, Bit17-22: 倒数第5位, Bit23-28: 倒数第6位
        """
        c4 = ARINC429Decoder.extract_data_bits(word, 11, 16)
        c5 = ARINC429Decoder.extract_data_bits(word, 17, 22)
        c6 = ARINC429Decoder.extract_data_bits(word, 23, 28)
        return (ARINC429Decoder._decode_flight_char(c6) +
                ARINC429Decoder._decode_flight_char(c5) +
                ARINC429Decoder._decode_flight_char(c4))

    @staticmethod
    def decode_flight_id_3(word: int) -> str:
        """
        解码航班号3 (Label 236): 字符7-8
        Bit11-16: 倒数第7位, Bit17-22: 倒数第8位(最高位)
        """
        c7 = ARINC429Decoder.extract_data_bits(word, 11, 16)
        c8 = ARINC429Decoder.extract_data_bits(word, 17, 22)
        return (ARINC429Decoder._decode_flight_char(c8) +
                ARINC429Decoder._decode_flight_char(c7))

    @staticmethod
    def decode_barometric_altitude(word: int) -> float:
        """
        解码绝对气压高度 (Label 203)
        BNR, 范围 -1500~30000 ft, LSB=0.25 ft, 17位 (Bit11-28), 有符号(Bit29)
        """
        data = ARINC429Decoder.extract_data_bits(word, 11, 28)
        sign = ARINC429Decoder.extract_sign_bit(word)
        altitude = data * 0.25
        if sign:
            altitude = -altitude
        return altitude

    @staticmethod
    def decode_true_airspeed(word: int) -> float:
        """
        解码真空速 (Label 210)
        BNR, 范围 27~450 kn, LSB=0.125 kn, 15位 (Bit11-28), 无符号
        """
        data = ARINC429Decoder.extract_data_bits(word, 11, 28)
        return data * 0.125

    @staticmethod
    def decode_vertical_rate(word: int) -> float:
        """
        解码升降速度 (Label 212)
        BNR, 范围 -6000~6000 ft/min, LSB=3 ft/min, 12位 (Bit11-28), 有符号(Bit29)
        """
        data = ARINC429Decoder.extract_data_bits(word, 11, 28)
        sign = ARINC429Decoder.extract_sign_bit(word)
        rate = data * 3.0
        if sign:
            rate = -rate
        return rate

    @staticmethod
    def decode_intruder_heading(word: int) -> float:
        """解码入侵机真航向 (Label 133), BNR, 0~360°"""
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        return data * 0.000171661376953125

    @staticmethod
    def decode_intruder_squawk(word: int) -> str:
        """解码入侵机识别代码 (Label 162), BCD"""
        return ARINC429Decoder.decode_squawk_code(word)

    @staticmethod
    def decode_intruder_flight_id(word: int) -> int:
        """解码入侵机航班号 (Label 134/135/136/137), BNR, 返回原始数据"""
        return ARINC429Decoder.extract_data_bits(word, 9, 29)

    @staticmethod
    def decode_intruder_ground_speed(word: int) -> float:
        """解码入侵机地速 (Label 141), BNR"""
        data = ARINC429Decoder.extract_data_bits(word, 9, 28)
        return data * 0.0078125

    @staticmethod
    def decode_intruder_lat_lon_12bit(word: int) -> int:
        """解码入侵机纬度/经度 12位分量 (Label 142/143/144/145), BNR"""
        return ARINC429Decoder.extract_data_bits(word, 9, 20)

    @staticmethod
    def decode_intruder_smode_addr_12bit(word: int) -> int:
        """解码入侵机S模式地址 12位分量 (Label 146/147), BNR"""
        return ARINC429Decoder.extract_data_bits(word, 9, 20)

    @staticmethod
    def decode_intruder_vert_speed(word: int) -> float:
        """解码入侵机垂直速度 (Label 151), BNR"""
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        sign = ARINC429Decoder.extract_sign_bit(word)
        v = data * 0.00048828125
        if sign:
            v = -v
        return v

    @staticmethod
    def decode_intruder_velocity(word: int) -> float:
        """解码入侵机北/东向速度 (Label 152/153), BNR"""
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        sign = ARINC429Decoder.extract_sign_bit(word)
        v = data * 0.00048828125
        if sign:
            v = -v
        return v

    @staticmethod
    def decode_intruder_nav_category(word: int) -> int:
        """解码入侵机导航精度/完整性类别 (Label 154/155), BNR, 返回原始值"""
        return ARINC429Decoder.extract_data_bits(word, 9, 29)

    @staticmethod
    def decode_intruder_status(word: int) -> int:
        """解码入侵机状况消息 (Label 156), BNR, 返回原始值"""
        return ARINC429Decoder.extract_data_bits(word, 9, 29)

    @staticmethod
    def decode_intruder_altitude(word: int) -> float:
        """解码入侵机高度 (Label 157), BNR"""
        data = ARINC429Decoder.extract_data_bits(word, 9, 29)
        sign = ARINC429Decoder.extract_sign_bit(word)
        alt = data * 0.125
        if sign:
            alt = -alt
        return alt

    @staticmethod
    def decode_intruder_timestamp(word: int) -> int:
        """解码入侵机时标 (Label 160/161), BNR, 返回原始值"""
        return ARINC429Decoder.extract_data_bits(word, 9, 29)

    @staticmethod
    def decode_start_stop_word(word: int) -> int:
        """解码发送起始/终止字 (Label 357), BNR, 返回原始值"""
        return ARINC429Decoder.extract_data_bits(word, 9, 29)

    @staticmethod
    def decode_software_version(word: int) -> str:
        """解码软件版本号 (Label 233), BCD"""
        d1 = ARINC429Decoder.extract_data_bits(word, 9, 12)
        d2 = ARINC429Decoder.extract_data_bits(word, 13, 16)
        d3 = ARINC429Decoder.extract_data_bits(word, 17, 20)
        d4 = ARINC429Decoder.extract_data_bits(word, 21, 24)
        d5 = ARINC429Decoder.extract_data_bits(word, 25, 28)
        return f"{d5}{d4}{d3}.{d2}{d1}"

    @staticmethod
    def decode_software_date(word: int) -> str:
        """解码软件版本日期 (Label 234), BCD"""
        d1 = ARINC429Decoder.extract_data_bits(word, 9, 12)
        d2 = ARINC429Decoder.extract_data_bits(word, 13, 16)
        d3 = ARINC429Decoder.extract_data_bits(word, 17, 20)
        d4 = ARINC429Decoder.extract_data_bits(word, 21, 24)
        d5 = ARINC429Decoder.extract_data_bits(word, 25, 28)
        return f"{d5}{d4}{d3}{d2}{d1}"
