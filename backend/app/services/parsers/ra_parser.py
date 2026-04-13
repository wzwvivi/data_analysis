# -*- coding: utf-8 -*-
"""
无线电高度表 (RA) 解析器

实现依据：
- 转换后的ICD6.0.1（260306）.xlsx（端口/偏移）
- 无线电高度表429协议-V1.0.docx（Label定义）

解析端口：
- RA1: 7007(L164/L165), 7008(L270), 7009(L350)
- RA2: 7010(L164/L165), 7011(L270), 7012(L350)

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
    3: "正常工作",
}

_RA_SDI_TEXT = {
    0: "不使用",
    1: "左侧",
    2: "右侧",
    3: "中心",
}


_LABEL_DEFS: Dict[int, Dict[str, Any]] = {
    0o164: {"col": "alt_bnr", "enc": "bnr", "lsb_bit": 13, "msb_bit": 29, "lsb_val": 0.125, "signed": True},
    0o165: {"col": "alt_bcd", "enc": "bcd_alt"},
    0o270: {"col": "discrete", "enc": "discrete_270"},
    0o350: {"col": "bit_status", "enc": "discrete_350"},
}

_PORT_LABELS: Dict[int, List[int]] = {
    7007: [0o164, 0o165],
    7008: [0o270],
    7009: [0o350],
    7010: [0o164, 0o165],
    7011: [0o270],
    7012: [0o350],
}

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)


def _yn_cn(v: int, zero: str, one: str) -> str:
    return one if v == 1 else zero


def _decode_bcd_alt(word: int) -> float:
    d = ARINC429Decoder.extract_data_bits
    tenths = d(word, 11, 14)
    ones = d(word, 15, 18)
    tens = d(word, 19, 22)
    hundreds = d(word, 23, 26)
    thousands = d(word, 27, 29)
    value = thousands * 1000 + hundreds * 100 + tens * 10 + ones + tenths * 0.1
    ssm = ARINC429Decoder.extract_ssm(word)
    if ssm == 3:
        value = -value
    return value


def _decode_bnr_twos_complement(word: int, lsb_bit: int, msb_bit: int, lsb_value: float) -> float:
    """Decode signed BNR field using in-field two's complement."""
    raw = ARINC429Decoder.extract_data_bits(word, lsb_bit, msb_bit)
    nbits = msb_bit - lsb_bit + 1
    sign_mask = 1 << (nbits - 1)
    if raw & sign_mask:
        raw -= (1 << nbits)
    return raw * lsb_value


def _columns_for_label(label: int) -> List[str]:
    pfx = label_prefix(label)
    cols: List[str] = []
    if label == 0o164:
        cols.extend([f"{pfx}.alt_bnr", f"{pfx}.inhibit_selftest", f"{pfx}.inhibit_selftest_enum"])
    elif label == 0o165:
        cols.extend([f"{pfx}.alt_bcd", f"{pfx}.alt_bcd_sign", f"{pfx}.alt_bcd_sign_enum"])
    elif label == 0o270:
        cols.extend([
            f"{pfx}.discrete", f"{pfx}.discrete_enum",
            f"{pfx}.inhibit_selftest", f"{pfx}.inhibit_selftest_enum",
            f"{pfx}.aid20", f"{pfx}.aid20_enum",
            f"{pfx}.aid40", f"{pfx}.aid40_enum",
            f"{pfx}.aid57", f"{pfx}.aid57_enum",
            f"{pfx}.aid_check", f"{pfx}.aid_check_enum",
            f"{pfx}.alt_valid", f"{pfx}.alt_valid_enum",
            f"{pfx}.selftest", f"{pfx}.selftest_enum",
        ])
    elif label == 0o350:
        cols.extend([
            f"{pfx}.bit_status", f"{pfx}.bit_status_enum",
            f"{pfx}.ra_status", f"{pfx}.ra_status_enum",
            f"{pfx}.source_signal", f"{pfx}.source_signal_enum",
            f"{pfx}.aid_detect", f"{pfx}.aid_detect_enum",
            f"{pfx}.fpga_monitor", f"{pfx}.fpga_monitor_enum",
            f"{pfx}.volt_5v", f"{pfx}.volt_5v_enum",
            f"{pfx}.volt_15v", f"{pfx}.volt_15v_enum",
            f"{pfx}.volt_28v", f"{pfx}.volt_28v_enum",
            f"{pfx}.tx_channel", f"{pfx}.tx_channel_enum",
            f"{pfx}.rx_channel_a", f"{pfx}.rx_channel_a_enum",
            f"{pfx}.rx_channel_b", f"{pfx}.rx_channel_b_enum",
            f"{pfx}.tx429_ch1", f"{pfx}.tx429_ch1_enum",
            f"{pfx}.tx429_ch2", f"{pfx}.tx429_ch2_enum",
            f"{pfx}.rx_antenna", f"{pfx}.rx_antenna_enum",
            f"{pfx}.tx_antenna", f"{pfx}.tx_antenna_enum",
            f"{pfx}.clock1", f"{pfx}.clock1_enum",
            f"{pfx}.clock2", f"{pfx}.clock2_enum",
        ])
    cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
    return cols


def _build_output_columns() -> List[str]:
    cols: List[str] = ["timestamp", "ra_id", "ra_id_cn"]
    for label in sorted(_LABEL_DEFS.keys()):
        cols.extend(_columns_for_label(label))
    return cols


_OUTPUT_COLUMNS = _build_output_columns()


@ParserRegistry.register
class RAParser(Arinc429Mixin, BaseParser):
    parser_key = "ra_v1.0"
    name = "无线电高度表"
    supported_ports = [7007, 7008, 7009, 7010, 7011, 7012]

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
        return ["timestamp", "ra_id", "ra_id_cn"]

    def _columns_for_label(self, label: int) -> List[str]:
        return _columns_for_label(label)

    # ------------------------------------------------------------------
    # 解码逻辑（RA 专有）
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        defn = _LABEL_DEFS.get(label)
        if defn is None:
            return

        pfx = label_prefix(label)
        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)

        record["ra_id"] = sdi
        record["ra_id_cn"] = _RA_SDI_TEXT.get(sdi, f"SDI={sdi}")
        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = _SSM_TEXT.get(ssm, str(ssm))
        record[f"{pfx}.parity"] = parity_ok(word)

        if label == 0o164:
            # RA 的 BNR 高度字段按字段位宽二补码解码（避免“独立符号位”误判导致大负值）。
            alt = _decode_bnr_twos_complement(
                word=word,
                msb_bit=defn["msb_bit"],
                lsb_bit=defn["lsb_bit"],
                lsb_value=defn["lsb_val"],
            )
            inhibit = ARINC429Decoder.extract_data_bits(word, 11, 11)
            record[f"{pfx}.alt_bnr"] = round(alt, 6)
            record[f"{pfx}.inhibit_selftest"] = inhibit
            record[f"{pfx}.inhibit_selftest_enum"] = _yn_cn(inhibit, "地面无效", "空中有效")

        elif label == 0o165:
            alt_bcd = _decode_bcd_alt(word)
            sign = self.decoder.extract_ssm(word)
            record[f"{pfx}.alt_bcd"] = round(alt_bcd, 6)
            record[f"{pfx}.alt_bcd_sign"] = sign
            sign_text = {
                0: "正",
                1: "非计算数据",
                2: "功能测试",
                3: "负",
            }.get(sign, str(sign))
            record[f"{pfx}.alt_bcd_sign_enum"] = sign_text

        elif label == 0o270:
            raw = ARINC429Decoder.extract_data_bits(word, 11, 29)
            inhibit = ARINC429Decoder.extract_data_bits(word, 11, 11)
            aid20 = ARINC429Decoder.extract_data_bits(word, 13, 13)
            aid40 = ARINC429Decoder.extract_data_bits(word, 14, 14)
            aid57 = ARINC429Decoder.extract_data_bits(word, 15, 15)
            aid_chk = ARINC429Decoder.extract_data_bits(word, 16, 16)
            alt_valid = ARINC429Decoder.extract_data_bits(word, 19, 19)
            selftest = ARINC429Decoder.extract_data_bits(word, 26, 26)
            record[f"{pfx}.discrete"] = raw
            record[f"{pfx}.inhibit_selftest"] = inhibit
            record[f"{pfx}.inhibit_selftest_enum"] = _yn_cn(inhibit, "地面无效", "空中有效")
            record[f"{pfx}.aid20"] = aid20
            record[f"{pfx}.aid20_enum"] = _yn_cn(aid20, "接地", "开路")
            record[f"{pfx}.aid40"] = aid40
            record[f"{pfx}.aid40_enum"] = _yn_cn(aid40, "接地", "开路")
            record[f"{pfx}.aid57"] = aid57
            record[f"{pfx}.aid57_enum"] = _yn_cn(aid57, "接地", "开路")
            record[f"{pfx}.aid_check"] = aid_chk
            record[f"{pfx}.aid_check_enum"] = _yn_cn(aid_chk, "接地", "开路")
            record[f"{pfx}.alt_valid"] = alt_valid
            record[f"{pfx}.alt_valid_enum"] = _yn_cn(alt_valid, "无效", "有效")
            record[f"{pfx}.selftest"] = selftest
            record[f"{pfx}.selftest_enum"] = _yn_cn(selftest, "无效", "有效")
            record[f"{pfx}.discrete_enum"] = (
                f"高度数据:{record[f'{pfx}.alt_valid_enum']},"
                f"自检:{record[f'{pfx}.selftest_enum']},"
                f"AID20:{record[f'{pfx}.aid20_enum']},"
                f"AID40:{record[f'{pfx}.aid40_enum']},"
                f"AID57:{record[f'{pfx}.aid57_enum']}"
            )

        elif label == 0o350:
            raw = ARINC429Decoder.extract_data_bits(word, 11, 29)
            b = lambda x: ARINC429Decoder.extract_data_bits(word, x, x)  # noqa: E731
            fields = {
                "ra_status": (11, "正常", "故障"),
                "source_signal": (12, "正常", "异常"),
                "aid_detect": (13, "正常", "错误"),
                "fpga_monitor": (14, "正常", "异常"),
                "volt_5v": (15, "电压正常", "电压异常"),
                "volt_15v": (16, "电压正常", "电压异常"),
                "volt_28v": (17, "电压正常", "电压异常"),
                "tx_channel": (18, "正常", "故障"),
                "rx_channel_a": (19, "正常", "故障"),
                "rx_channel_b": (20, "正常", "故障"),
                "tx429_ch1": (21, "正常", "故障"),
                "tx429_ch2": (22, "正常", "故障"),
                "rx_antenna": (25, "已接", "未接"),
                "tx_antenna": (26, "已接", "未接"),
                "clock1": (27, "正常", "故障"),
                "clock2": (28, "正常", "故障"),
            }
            record[f"{pfx}.bit_status"] = raw
            summary_parts: List[str] = []
            for name, (bit_pos, ztxt, otxt) in fields.items():
                v = b(bit_pos)
                record[f"{pfx}.{name}"] = v
                record[f"{pfx}.{name}_enum"] = _yn_cn(v, ztxt, otxt)
                if v == 1:
                    summary_parts.append(f"{name}:{otxt}")
            record[f"{pfx}.bit_status_enum"] = "正常" if not summary_parts else "异常:" + ",".join(summary_parts)
