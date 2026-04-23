# -*- coding: utf-8 -*-
"""
S/ADS-5 大气数据系统 (ADC/ADRU) 解析器（bundle-only）

实现依据：大气系统通讯协议-调试前最终版协议-V2.2.docx
所有 Label bits / 编码 / 单位 / 枚举等定义均由 DeviceBundle 承载，本模块只
持有：
  - 本 parser 负责的 label 集合（_LABEL_INTS）
  - 端口→parser 的 supported_ports
  - 设备级 ID 映射 (ADRU#1 / #2 / #3 等) 与部分 parser 侧的复合摘要
    （起飞/巡航/着陆 合成、BIT 故障名列表等）。
"""
from typing import Any, Dict, List, Optional

from .base import BaseParser, ParserRegistry
from .arinc429 import ARINC429Decoder
from .arinc429_mixin import (
    Arinc429Mixin, label_prefix, parity_ok, build_field_name_to_label,
)

_SSM_TEXT = {0: "故障告警", 1: "无计算数据", 2: "功能测试", 3: "正常数据"}


# ---------------------------------------------------------------------------
# parser 负责的 label 集合（八进制）；实际字段定义来自 DeviceBundle。
# ---------------------------------------------------------------------------
_LABEL_INTS = (
    # A. 表决后 BNR
    0o102, 0o103, 0o203, 0o205, 0o206, 0o207, 0o210, 0o211, 0o212, 0o213,
    0o221, 0o226,
    # B. 源数据 BNR
    0o176, 0o177, 0o244, 0o245, 0o246, 0o303, 0o304, 0o305, 0o306, 0o307,
    0o310, 0o311, 0o312, 0o313, 0o314, 0o321, 0o326,
    # C1. 自检状态字 & 其他离散量
    0o137, 0o235, 0o236, 0o237, 0o240, 0o241, 0o242, 0o243,
    # C2/3. BCD + 回报
    0o233, 0o234, 0o350, 0o364,
)

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_INTS)


# ---------------------------------------------------------------------------
# 设备级 ID / 枚举（不属于 bundle 字段语义；属于 parser 侧设备归属）
# ---------------------------------------------------------------------------

_ADRU_ID_MAP = {0: "ADRU#1", 1: "ADRU#2", 2: "ADRU#3", 3: "ADRU#?"}

_HEAT_CMD_MAP = {
    0: "强制不加温",
    1: "强制加温",
    2: "自动控制",
    3: "保留",
}


# ---------------------------------------------------------------------------
# BIT 故障位名（parser 侧聚合：把每个 bit 位的"故障名"拼成一段字符串）。
# 这里的 bit→名 对照表是 ICD 文档中"每位含义"的硬信息，属于 parser 选择的
# 聚合视图，不宜塞进 bundle 的通用 discrete_bits.values（values 是"该 bit
# 的取值文案"，不是"位名"）。保留在 parser 侧即可。
# ---------------------------------------------------------------------------

_PBIT_BITS = [
    (11, "FLASH检测"), (12, "RAM检测"), (13, "储能电容检测"),
    (14, "计算有效性检测"), (15, "429通道1检测"), (16, "429通道2检测"),
    (17, "429通道3检测"), (18, "429通道4检测"), (19, "铁电检测"),
]

_CBIT1_BITS = [
    (11, "左静压ADM"), (12, "右静压ADM"), (13, "总压ADM"),
    (14, "迎角传感器"), (15, "侧滑角传感器"), (16, "总温传感器"),
    (17, "ADRU"), (18, "左静压系数读取"), (19, "左静压频率1"),
    (20, "左静压频率2"), (21, "左静压超限"), (22, "右静压系数读取"),
    (23, "右静压频率1"), (24, "右静压频率2"), (25, "右静压超限"),
    (26, "总压系数"), (27, "总压频率1"), (28, "总压频率2"), (29, "总压超限"),
]

_CBIT2_BITS = [
    (11, "总压加温"), (12, "迎角超限"), (13, "迎角加温"),
    (14, "总温开路"), (15, "总温短路"), (16, "总温超限"),
    (17, "侧滑角超限"), (18, "侧滑角加温"), (19, "指示空速超限"),
    (20, "校准空速超限"), (21, "真空速超限"), (22, "升降速度超限"),
    (23, "马赫数超限"), (24, "绝对气压高度超限"), (25, "QNH高度超限"),
    (26, "QFE高度超限"), (27, "左静压总压相关性"), (28, "右静压总压相关性"),
    (29, "轮载离散量"),
]

_CBIT3_BITS = [
    (11, "外部1#429"), (12, "外部2#429"), (13, "外部3#429"),
    (14, "备用"), (15, "外部1#422"), (16, "外部2#422"),
    (17, "+15V电源"), (18, "左静压ADM通讯"), (19, "右静压ADM通讯"),
    (20, "总压ADM通讯"), (21, "AOA通讯"), (22, "AOS通讯"),
    (23, "AD模块"),
]


def _bit_fault_summary(word: int, bit_defs: list) -> str:
    faults = []
    for bit_pos, name in bit_defs:
        if ARINC429Decoder.extract_data_bits(word, bit_pos, bit_pos):
            faults.append(name)
    return "正常" if not faults else "故障:" + ",".join(faults)


def _decode_bcd_pressure(word: int) -> Optional[float]:
    d = ARINC429Decoder.extract_data_bits
    tenths   = d(word, 11, 14)
    ones     = d(word, 15, 18)
    tens     = d(word, 19, 22)
    hundreds = d(word, 23, 26)
    thousands = d(word, 27, 29) & 0x07
    if any(v > 9 for v in (tenths, ones, tens, hundreds)):
        return None
    return thousands * 1000 + hundreds * 100 + tens * 10 + ones + tenths * 0.1


def _decode_bcd_sw_version(word: int) -> Optional[str]:
    d = ARINC429Decoder.extract_data_bits
    hundredths_lsb = d(word, 11, 11)
    hundredths_rest = d(word, 12, 14)
    hundredths = (hundredths_rest << 1) | hundredths_lsb
    tenths_lsb = d(word, 15, 15)
    tenths_rest = d(word, 16, 18)
    tenths = (tenths_rest << 1) | tenths_lsb
    ones_lsb = d(word, 19, 19)
    ones_rest = d(word, 20, 22)
    ones = (ones_rest << 1) | ones_lsb
    if any(v > 9 for v in (hundredths, tenths, ones)):
        raw = d(word, 11, 22)
        return f"0x{raw:03X}"
    return f"{ones}.{tenths}{hundredths}"


# ---------------------------------------------------------------------------
# 解析器主类
# ---------------------------------------------------------------------------

@ParserRegistry.register
class ADCParser(Arinc429Mixin, BaseParser):
    """S/ADS-5 大气数据系统解析器 (adc_v2.2)"""

    parser_key = "adc_v2.2"
    name = "大气数据系统"
    supported_ports: List[int] = [
        7001, 7002, 7003, 7022, 7023, 7024, 7025, 7026, 7027,
        8003, 8004, 8005, 8006, 8007, 8008,
    ]

    _LABEL_INTS = _LABEL_INTS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def _common_columns(self) -> List[str]:
        return ["timestamp", "adru_id", "adru_id_cn"]

    def _ssm_text(self, ssm: int) -> str:
        return _SSM_TEXT.get(int(ssm), str(ssm))

    def _write_device_id(self, record: Dict[str, Any], sdi: int) -> None:
        record["adru_id"] = sdi
        record["adru_id_cn"] = _ADRU_ID_MAP.get(sdi, f"SDI={sdi}")

    # ------------------------------------------------------------------
    # bundle-driven 解码
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        bundle_label = self._get_bundle_label(label)
        if bundle_label is None:
            return

        pfx = label_prefix(label)
        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)
        self._write_device_id(record, sdi)
        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = self._ssm_text(ssm)
        record[f"{pfx}.parity"] = parity_ok(word)

        self._decode_with_bundle(record, word, self._current_port, bundle_label, pfx)
        self._compose_summary(record, label, pfx, word=word, bundle_label=bundle_label)

    # ------------------------------------------------------------------
    # ADC 侧复合摘要：bit 聚合 / BCD 文本 / 气压文本等
    # ------------------------------------------------------------------
    def _compose_summary(
        self,
        record: Dict[str, Any],
        label: int,
        pfx: str,
        word: Optional[int] = None,
        bundle_label: Any = None,
    ) -> None:
        if bundle_label is None:
            bundle_label = self._get_bundle_label(label)
        col = str(getattr(bundle_label, "name", "") or "").strip() if bundle_label else ""
        if not col:
            return

        if label in (0o240, 0o241, 0o242, 0o243):
            bit_defs = {
                0o240: _PBIT_BITS,
                0o241: _CBIT1_BITS,
                0o242: _CBIT2_BITS,
                0o243: _CBIT3_BITS,
            }[label]
            if word is None:
                return
            record[f"{pfx}.{col}_enum"] = _bit_fault_summary(word, bit_defs)
            return

        if label == 0o137:
            if word is None:
                return
            b11 = ARINC429Decoder.extract_data_bits(word, 11, 11)
            b12 = ARINC429Decoder.extract_data_bits(word, 12, 12)
            b13 = ARINC429Decoder.extract_data_bits(word, 13, 13)
            t = "有效" if b11 else "无效"
            c = "有效" if b12 else "无效"
            l = "有效" if b13 else "无效"
            record[f"{pfx}.{col}_enum"] = f"起飞:{t},巡航:{c},着陆:{l}"
            return

        if label == 0o236:
            v = record.get(f"{pfx}.{col}")
            if v is not None:
                record[f"{pfx}.{col}_enum"] = "启动自检" if int(v) == 1 else "不自检"
            return

        if label == 0o237:
            v = record.get(f"{pfx}.{col}")
            if v is not None:
                record[f"{pfx}.{col}_enum"] = _HEAT_CMD_MAP.get(int(v), f"未知({v})")
            return

        if label == 0o235:
            if word is None:
                return
            b11 = ARINC429Decoder.extract_data_bits(word, 11, 11)
            record[f"{pfx}.{col}_enum"] = "承压" if b11 == 1 else "不承压"
            return

        if label == 0o350:
            if word is None:
                return
            raw_int = ARINC429Decoder.extract_data_bits(word, 11, 28)
            record[f"{pfx}.{col}"] = raw_int
            record[f"{pfx}.{col}_enum"] = _decode_bcd_sw_version(word)
            return

        if label in (0o233, 0o234):
            if word is None:
                return
            val = _decode_bcd_pressure(word)
            record[f"{pfx}.{col}"] = val
            record[f"{pfx}.{col}_enum"] = f"{val} hPa" if val is not None else "无效"
            return
