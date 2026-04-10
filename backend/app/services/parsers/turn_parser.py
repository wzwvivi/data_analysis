# -*- coding: utf-8 -*-
"""
前轮转弯系统 (Turn/LS1) 解析器

实现依据：
- 转换后的ICD6.0.1（260306）.xlsx（端口/Label映射）
- 3_转弯系统ARINC429通讯协议_V2_20251121.docx（Label定义）

解析端口：
- 7019: LS1_A429Tx_01
- 7020: LS1_A429Tx_02

列名统一为 label_XXX.字段 格式，并为每个 Label 输出：
- .sdi / .ssm / .ssm_enum / .parity
"""
from typing import Any, Dict, List, Optional

from .base import BaseParser, FieldLayout, ParserRegistry
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

_LABEL_DEFS: Dict[int, Dict[str, Any]] = {
    # ── 上行 (SCU → RDIU) ──
    0o111: {"col": "nw_angle", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.014653, "signed": True},
    0o112: {"col": "left_handwheel", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.021978, "signed": True},
    0o113: {"col": "right_handwheel", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.021978, "signed": True},
    0o114: {"col": "zero_offset", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.010986, "signed": True},
    0o154: {"col": "control", "enc": "discrete_154"},
    0o212: {"col": "pedal_cmd_echo", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.014653, "signed": True},
    0o244: {"col": "status", "enc": "discrete_244"},
    0o314: {"col": "fault_word", "enc": "discrete_314"},
    # ── 下行 (FCM → SCU) ──
    0o115: {"col": "nw_steer_cmd", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.014653, "signed": True},
    0o116: {"col": "nw_steer_cmd", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.014653, "signed": True},
    0o117: {"col": "nw_steer_cmd", "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.014653, "signed": True},
    0o354: {"col": "fcm_control", "enc": "discrete_354"},
    0o355: {"col": "fcm_control", "enc": "discrete_354"},
    0o356: {"col": "fcm_control", "enc": "discrete_354"},
    0o374: {"col": "ground_speed", "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125, "signed": False},
    0o375: {"col": "ground_speed", "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125, "signed": False},
    0o376: {"col": "ground_speed", "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125, "signed": False},
}

_PORT_LABELS: Dict[int, List[int]] = {
    7019: [0o111, 0o112, 0o113, 0o114, 0o154, 0o212, 0o244, 0o314],
    7020: [0o111, 0o112, 0o113, 0o114, 0o154, 0o212, 0o244, 0o314],
    8017: [0o115, 0o354, 0o374],
    8018: [0o116, 0o355, 0o375],
    8019: [0o117, 0o356, 0o376],
}

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)


def _yn(v: int, on_text: str, off_text: str) -> str:
    return on_text if v == 1 else off_text


def _columns_for_label(label: int) -> List[str]:
    pfx = label_prefix(label)
    cols: List[str] = []

    if label in (0o111, 0o112, 0o113, 0o114, 0o212,
                  0o115, 0o116, 0o117, 0o374, 0o375, 0o376):
        cols.append(f"{pfx}.{_LABEL_DEFS[label]['col']}")
    elif label == 0o154:
        cols.extend([
            f"{pfx}.control", f"{pfx}.control_enum",
            f"{pfx}.zero_cmd", f"{pfx}.zero_cmd_enum",
            f"{pfx}.steer_disc", f"{pfx}.steer_disc_enum",
            f"{pfx}.park_brk_on", f"{pfx}.park_brk_on_enum",
        ])
    elif label == 0o244:
        cols.extend([
            f"{pfx}.status", f"{pfx}.status_enum",
            f"{pfx}.pedal_release", f"{pfx}.pedal_release_enum",
            f"{pfx}.work_state", f"{pfx}.work_state_enum",
            f"{pfx}.tow_state", f"{pfx}.tow_state_enum",
            f"{pfx}.sw_major", f"{pfx}.sw_minor",
            f"{pfx}.sw_version", f"{pfx}.sw_version_enum",
        ])
    elif label == 0o314:
        cols.extend([
            f"{pfx}.fault_word", f"{pfx}.fault_word_enum",
            f"{pfx}.left_hw_fault", f"{pfx}.left_hw_fault_enum",
            f"{pfx}.right_hw_fault", f"{pfx}.right_hw_fault_enum",
            f"{pfx}.a429_comm_fault", f"{pfx}.a429_comm_fault_enum",
            f"{pfx}.nw_work_fault", f"{pfx}.nw_work_fault_enum",
            f"{pfx}.tow_overtravel", f"{pfx}.tow_overtravel_enum",
        ])
    elif label in (0o354, 0o355, 0o356):
        cols.extend([
            f"{pfx}.fcm_control", f"{pfx}.fcm_control_enum",
            f"{pfx}.zero_cmd", f"{pfx}.zero_cmd_enum",
            f"{pfx}.steer_disc", f"{pfx}.steer_disc_enum",
        ])

    cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
    return cols


def _build_output_columns() -> List[str]:
    cols = ["timestamp", "scu_id", "scu_id_cn"]
    for label in sorted(_LABEL_DEFS.keys()):
        cols.extend(_columns_for_label(label))
    return cols


_OUTPUT_COLUMNS = _build_output_columns()


@ParserRegistry.register
class TurnParser(Arinc429Mixin, BaseParser):
    parser_key = "turn_v2"
    name = "前轮转弯系统"
    supported_ports = [7019, 7020, 8017, 8018, 8019]

    _LABEL_DEFS = _LABEL_DEFS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL
    _OUTPUT_COLUMNS = _OUTPUT_COLUMNS
    _PORT_LABELS = _PORT_LABELS

    OUTPUT_COLUMNS = _OUTPUT_COLUMNS

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        return port in self.supported_ports

    def _common_columns(self) -> List[str]:
        return ["timestamp", "scu_id", "scu_id_cn"]

    def _columns_for_label(self, label: int) -> List[str]:
        return _columns_for_label(label)

    # ------------------------------------------------------------------
    # 解码逻辑（Turn 专有）
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        defn = _LABEL_DEFS.get(label)
        if defn is None:
            return

        pfx = label_prefix(label)
        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)
        parity = parity_ok(word)

        record["scu_id"] = sdi
        record["scu_id_cn"] = _SCU_SDI_TEXT.get(sdi, f"SDI={sdi}")
        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = _SSM_TEXT.get(ssm, str(ssm))
        record[f"{pfx}.parity"] = parity

        if defn["enc"] == "bnr":
            value = self.decoder.decode_bnr_with_lsb(
                word,
                msb_bit=defn["msb_bit"],
                lsb_bit=defn["lsb_bit"],
                lsb_value=defn["lsb_val"],
                signed=defn.get("signed", True),
            )
            record[f"{pfx}.{defn['col']}"] = round(value, 8)

        elif defn["enc"] == "discrete_354":
            b14 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            b15 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            raw = (b15 << 1) | b14
            record[f"{pfx}.fcm_control"] = raw
            record[f"{pfx}.fcm_control_enum"] = f"调零={b14},转弯断开={b15}"
            record[f"{pfx}.zero_cmd"] = b14
            record[f"{pfx}.zero_cmd_enum"] = _yn(b14, "调零", "无效")
            record[f"{pfx}.steer_disc"] = b15
            record[f"{pfx}.steer_disc_enum"] = _yn(b15, "转弯断开", "无效")

        elif defn["enc"] == "discrete_154":
            b13 = ARINC429Decoder.extract_data_bits(word, 13, 13)
            b14 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            b15 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            raw = (b15 << 2) | (b14 << 1) | b13
            record[f"{pfx}.control"] = raw
            record[f"{pfx}.control_enum"] = f"调零={b13},断开={b14},停留刹车={b15}"
            record[f"{pfx}.zero_cmd"] = b13
            record[f"{pfx}.zero_cmd_enum"] = _yn(b13, "调零", "无效")
            record[f"{pfx}.steer_disc"] = b14
            record[f"{pfx}.steer_disc_enum"] = _yn(b14, "转弯断开", "无效")
            record[f"{pfx}.park_brk_on"] = b15
            record[f"{pfx}.park_brk_on_enum"] = _yn(b15, "有效", "无效")

        elif defn["enc"] == "discrete_244":
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
            record[f"{pfx}.pedal_release"] = pedal_release
            record[f"{pfx}.pedal_release_enum"] = _yn(pedal_release, "解除状态", "正常状态")
            record[f"{pfx}.work_state"] = work_state
            record[f"{pfx}.work_state_enum"] = _WORK_STATE_TEXT.get(work_state, f"保留({work_state})")
            record[f"{pfx}.tow_state"] = tow_state
            record[f"{pfx}.tow_state_enum"] = _TOW_STATE_TEXT.get(tow_state, f"保留({tow_state})")
            record[f"{pfx}.sw_major"] = sw_major
            record[f"{pfx}.sw_minor"] = sw_minor
            record[f"{pfx}.sw_version"] = sw_major * 100 + sw_minor
            record[f"{pfx}.sw_version_enum"] = f"{sw_major}.{sw_minor}"

        elif defn["enc"] == "discrete_314":
            b14 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            b15 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            b16 = ARINC429Decoder.extract_data_bits(word, 16, 16)
            b17 = ARINC429Decoder.extract_data_bits(word, 17, 17)
            b18 = ARINC429Decoder.extract_data_bits(word, 18, 18)
            raw = ARINC429Decoder.extract_data_bits(word, 14, 18)
            faults = []
            if b14:
                faults.append("左手轮传感器和值故障")
            if b15:
                faults.append("右手轮传感器和值故障")
            if b16:
                faults.append("ARINC429通讯故障")
            if b17:
                faults.append("前轮工作故障")
            if b18:
                faults.append("牵引超行程")

            record[f"{pfx}.fault_word"] = raw
            record[f"{pfx}.fault_word_enum"] = "正常" if not faults else ("故障:" + ",".join(faults))
            record[f"{pfx}.left_hw_fault"] = b14
            record[f"{pfx}.left_hw_fault_enum"] = _yn(b14, "故障", "正常")
            record[f"{pfx}.right_hw_fault"] = b15
            record[f"{pfx}.right_hw_fault_enum"] = _yn(b15, "故障", "正常")
            record[f"{pfx}.a429_comm_fault"] = b16
            record[f"{pfx}.a429_comm_fault_enum"] = _yn(b16, "故障", "正常")
            record[f"{pfx}.nw_work_fault"] = b17
            record[f"{pfx}.nw_work_fault_enum"] = _yn(b17, "故障", "正常")
            record[f"{pfx}.tow_overtravel"] = b18
            record[f"{pfx}.tow_overtravel_enum"] = _yn(b18, "故障", "正常")
