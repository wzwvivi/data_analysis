# -*- coding: utf-8 -*-
"""
前轮转弯系统 (Turn/LS1) 解析器（bundle-only）

实现依据：
- 转换后的ICD6.0.1（260306）.xlsx（端口/Label映射）
- 3_转弯系统ARINC429通讯协议_V2_20251121.docx（Label 定义，承载在 DeviceBundle）

所有 Label bits / 编码 / values 枚举均由 DeviceBundle 提供。
本 parser 负责：
  - 声明可处理的 label 集合（_LABEL_INTS）
  - 设备级 scu_id 映射
  - 对 L154 / L244 / L314 / L354-L356 做 parser 侧聚合（raw 合成 / 故障文本）
"""
from typing import Any, Dict, List, Optional

from .base import BaseParser, ParserRegistry
from .arinc429 import ARINC429Decoder
from .arinc429_mixin import (
    Arinc429Mixin, label_prefix, parity_ok, build_field_name_to_label,
)

_SSM_TEXT = {
    0: "故障告警",
    1: "无计算数据",
    2: "功能测试",
    3: "正常数据",
}

_SCU_SDI_TEXT = {
    0: "通道0",
    1: "通道1",
    2: "通道2",
    3: "通道3",
}

_WORK_STATE_TEXT = {
    0b010: "转弯状态",
    0b011: "减摆状态",
    0b100: "调零状态",
}

_TOW_STATE_TEXT = {
    0b00: "牵引无效",
    0b01: "允许牵引",
    0b10: "禁止牵引",
}


_LABEL_INTS = (
    # 上行 (SCU → RDIU)
    0o111, 0o112, 0o113, 0o114, 0o154, 0o212, 0o244, 0o314,
    # 下行 (FCM → SCU)
    0o115, 0o116, 0o117, 0o354, 0o355, 0o356, 0o374, 0o375, 0o376,
)

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_INTS)


@ParserRegistry.register
class TurnParser(Arinc429Mixin, BaseParser):
    parser_key = "turn_v2"
    name = "前轮转弯系统"
    supported_ports = [7019, 7020, 8017, 8018, 8019]

    _LABEL_INTS = _LABEL_INTS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        return port in self.supported_ports

    def _common_columns(self) -> List[str]:
        return ["timestamp", "scu_id", "scu_id_cn"]

    def _ssm_text(self, ssm: int) -> str:
        return _SSM_TEXT.get(int(ssm), str(ssm))

    def _write_device_id(self, record: Dict[str, Any], sdi: int) -> None:
        record["scu_id"] = sdi
        record["scu_id_cn"] = _SCU_SDI_TEXT.get(sdi, f"SDI={sdi}")

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
        self._compose_summary(record, label, pfx, word=word)

    def _compose_summary(
        self,
        record: Dict[str, Any],
        label: int,
        pfx: str,
        word: Optional[int] = None,
    ) -> None:
        """Turn 各 label 的复合摘要列（读取 record 的原子列或 word）。"""
        if label in (0o354, 0o355, 0o356):
            if word is None:
                return
            b14 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            b15 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            record[f"{pfx}.fcm_control"] = (b15 << 1) | b14
            record[f"{pfx}.fcm_control_enum"] = f"调零={b14},转弯断开={b15}"
            return

        if label == 0o154:
            if word is None:
                return
            b13 = ARINC429Decoder.extract_data_bits(word, 13, 13)
            b14 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            b15 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            record[f"{pfx}.control"] = (b15 << 2) | (b14 << 1) | b13
            record[f"{pfx}.control_enum"] = f"调零={b13},断开={b14},停留刹车={b15}"
            return

        if label == 0o244:
            if word is None:
                return
            pedal_release = ARINC429Decoder.extract_data_bits(word, 12, 12)
            work_state = ARINC429Decoder.extract_data_bits(word, 14, 16)
            tow_state = ARINC429Decoder.extract_data_bits(word, 17, 18)
            sw_major = ARINC429Decoder.extract_data_bits(word, 19, 22)
            sw_minor = ARINC429Decoder.extract_data_bits(word, 23, 26)
            raw = ARINC429Decoder.extract_data_bits(word, 12, 26)
            record[f"{pfx}.status"] = raw
            record[f"{pfx}.status_enum"] = (
                f"脚蹬解除={pedal_release},工作状态={work_state},牵引状态={tow_state},"
                f"版本={sw_major}.{sw_minor}"
            )
            record[f"{pfx}.work_state"] = work_state
            if not record.get(f"{pfx}.work_state_enum"):
                record[f"{pfx}.work_state_enum"] = _WORK_STATE_TEXT.get(
                    work_state, f"保留({work_state})"
                )
            record[f"{pfx}.tow_state"] = tow_state
            if not record.get(f"{pfx}.tow_state_enum"):
                record[f"{pfx}.tow_state_enum"] = _TOW_STATE_TEXT.get(
                    tow_state, f"保留({tow_state})"
                )
            record[f"{pfx}.sw_major"] = sw_major
            record[f"{pfx}.sw_minor"] = sw_minor
            record[f"{pfx}.sw_version"] = sw_major * 100 + sw_minor
            record[f"{pfx}.sw_version_enum"] = f"{sw_major}.{sw_minor}"
            return

        if label == 0o314:
            faults = []
            for col, cn in (
                ("left_hw_fault", "左手轮传感器和值故障"),
                ("right_hw_fault", "右手轮传感器和值故障"),
                ("a429_comm_fault", "ARINC429通讯故障"),
                ("nw_work_fault", "前轮工作故障"),
                ("tow_overtravel", "牵引超行程"),
            ):
                if record.get(f"{pfx}.{col}") == 1:
                    faults.append(cn)
            record[f"{pfx}.fault_word_enum"] = (
                "正常" if not faults else "故障:" + ",".join(faults)
            )
            return
