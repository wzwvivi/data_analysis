# -*- coding: utf-8 -*-
"""
S/ADS-5 大气数据系统 (ADC/ADRU) 解析器

实现依据：大气系统通讯协议-调试前最终版协议-V2.2.docx
解析 ARINC 429 数据流，端口由 TSN 网络配置动态指定。

ADRU 发送的参数分为三大类：
 A. 表决后大气参数（12个 BNR，20ms，→ FCC + DIU）
 B. 源数据大气参数（17个 BNR，20ms，→ DIU）
 C. 自检/回报/版本（离散量 + BCD，100ms/1000ms，→ DIU/FCC）

所有 Label 编号均为八进制（ARINC 429 惯例）。
列名统一为 label_XXX.字段 格式。
"""
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout
from .arinc429 import ARINC429Decoder
from .arinc429_mixin import (
    Arinc429Mixin, label_prefix, parity_ok, build_field_name_to_label,
)

_SSM_TEXT = {0: "故障告警", 1: "无计算数据", 2: "功能测试", 3: "正常数据"}

# ---------------------------------------------------------------------------
#  ARINC 429 Label 定义表（数据驱动）
# ---------------------------------------------------------------------------

_LABEL_DEFS: Dict[int, dict] = {
    # ====== A. 表决后 BNR (ADRU → FCC + DIU) ======
    0o203: {"col": "voted_abs_alt",     "cn": "绝对气压高度(表决后)",     "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o103: {"col": "voted_qnh_alt",     "cn": "QNH高度(表决后)",          "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o102: {"col": "voted_qfe_alt",     "cn": "QFE高度(表决后)",          "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o205: {"col": "voted_mach",        "cn": "马赫数(表决后)",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.0000625,  "signed": True,  "unit": ""},
    0o206: {"col": "voted_ias",         "cn": "指示空速(表决后)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o207: {"col": "voted_cas",         "cn": "校准空速(表决后)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o210: {"col": "voted_tas",         "cn": "真空速(表决后)",           "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o212: {"col": "voted_vspeed",      "cn": "升降速度(表决后)",         "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 3.0,       "signed": True,  "unit": "ft/min"},
    0o211: {"col": "voted_tat",         "cn": "总温(表决后)",             "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o213: {"col": "voted_sat",         "cn": "静温(表决后)",             "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o221: {"col": "voted_aoa",         "cn": "迎角(表决后)",             "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},
    0o226: {"col": "voted_aos",         "cn": "侧滑角(表决后)",           "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},

    # ====== B. 源数据 BNR (ADRU → DIU) ======
    0o176: {"col": "src_left_sp",       "cn": "未修正左静压",             "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o177: {"col": "src_right_sp",      "cn": "未修正右静压",             "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o244: {"col": "src_total_p",       "cn": "总压",                     "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o245: {"col": "src_avg_sp",        "cn": "未修正平均静压",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o246: {"col": "src_avg_sp_corr",   "cn": "修正平均静压",             "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o303: {"col": "src_abs_alt",       "cn": "绝对气压高度(源数据)",     "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o304: {"col": "src_qnh_alt",       "cn": "QNH高度(源数据)",          "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o314: {"col": "src_qfe_alt",       "cn": "QFE高度(源数据)",          "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o305: {"col": "src_mach",          "cn": "马赫数(源数据)",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.0000625,  "signed": True,  "unit": ""},
    0o306: {"col": "src_ias",           "cn": "指示空速(源数据)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o307: {"col": "src_cas",           "cn": "校准空速(源数据)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o310: {"col": "src_tas",           "cn": "真空速(源数据)",           "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o312: {"col": "src_vspeed",        "cn": "升降速度(源数据)",         "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 3.0,       "signed": True,  "unit": "ft/min"},
    0o311: {"col": "src_tat",           "cn": "总温(源数据)",             "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o313: {"col": "src_sat",           "cn": "静温(源数据)",             "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o321: {"col": "src_aoa",           "cn": "迎角(源数据)",             "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},
    0o326: {"col": "src_aos",           "cn": "侧滑角(源数据)",           "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},

    # ====== C1. 自检状态字 (离散量，100ms) ======
    0o240: {"col": "pbit",              "cn": "上电自检状态字",           "enc": "discrete", "bits": (11, 19)},
    0o241: {"col": "cbit1",             "cn": "周期自检状态字1",          "enc": "discrete", "bits": (11, 29)},
    0o242: {"col": "cbit2",             "cn": "周期自检状态字2",          "enc": "discrete", "bits": (11, 29)},
    0o243: {"col": "cbit3",             "cn": "周期自检状态字3",          "enc": "discrete", "bits": (11, 23)},

    # ====== C2. 软件版本 (BCD, 1000ms) ======
    0o350: {"col": "sw_ver",            "cn": "软件版本",                 "enc": "bcd_version"},

    # ====== C3. 回报参数 (ADRU → DIU) ======
    0o233: {"col": "qnh_report",        "cn": "装订气压QNH回报",          "enc": "bcd_pressure"},
    0o234: {"col": "qfe_report",        "cn": "装订气压QFE回报",          "enc": "bcd_pressure"},
    0o137: {"col": "flap_status",       "cn": "襟翼状态回报",             "enc": "discrete", "bits": (11, 13)},
    0o364: {"col": "inertial_vrate",    "cn": "惯性垂直速率回报",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.01, "signed": True, "unit": "m/s²"},
    0o236: {"col": "maint_bit",         "cn": "维护自检指令回报",         "enc": "discrete", "bits": (11, 11)},
    0o237: {"col": "heat_cmd",          "cn": "强制加温指令回报",         "enc": "discrete", "bits": (11, 12)},
    0o235: {"col": "wow",               "cn": "轮载信号回报",             "enc": "discrete", "bits": (11, 12)},
}


def _needs_enum(defn: dict) -> bool:
    enc = defn["enc"]
    return enc in ("discrete", "bcd_pressure", "bcd_version")


def _columns_for_label(label_val: int) -> List[str]:
    defn = _LABEL_DEFS[label_val]
    pfx = label_prefix(label_val)
    cols = [f"{pfx}.{defn['col']}"]
    if _needs_enum(defn):
        cols.append(f"{pfx}.{defn['col']}_enum")
    cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
    return cols


def _build_output_columns() -> List[str]:
    cols = ["timestamp", "adru_id", "adru_id_cn"]
    for label_val in sorted(_LABEL_DEFS.keys()):
        cols.extend(_columns_for_label(label_val))
    return cols


_OUTPUT_COLUMNS = _build_output_columns()

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)

_ALL_LABELS = sorted(_LABEL_DEFS.keys())
_TX01_LABELS = [
    0o102, 0o103, 0o137, 0o176, 0o177, 0o203, 0o205, 0o206, 0o207,
    0o210, 0o211, 0o212, 0o213, 0o221, 0o226, 0o244, 0o245, 0o246,
    0o303, 0o304, 0o305, 0o306, 0o307, 0o310, 0o311, 0o312, 0o313,
    0o314, 0o321, 0o326, 0o350, 0o364,
]
_TX02_LABELS = [0o233, 0o234, 0o237]
_TX03_LABELS = [0o235, 0o236, 0o240, 0o241, 0o242, 0o243]

_PORT_LABELS: Dict[int, List[int]] = {
    7001: _TX01_LABELS, 7002: _TX01_LABELS, 7003: _TX01_LABELS,
    7022: _TX02_LABELS, 7024: _TX02_LABELS, 7026: _TX02_LABELS,
    7023: _TX03_LABELS, 7025: _TX03_LABELS, 7027: _TX03_LABELS,
}


# ---------------------------------------------------------------------------
#  BCD 气压解码（装订气压 QNH/QFE）
# ---------------------------------------------------------------------------

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
#  离散量 _enum 文字生成
# ---------------------------------------------------------------------------

_ADRU_ID_MAP = {0: "ADRU#1", 1: "ADRU#2", 2: "ADRU#3", 3: "ADRU#?"}

_HEAT_CMD_MAP = {
    0: "强制不加温",
    1: "强制加温",
    2: "自动控制",
    3: "保留",
}

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


def _discrete_enum(label: int, word: int, raw_val: int) -> str:
    if label == 0o240:
        return _bit_fault_summary(word, _PBIT_BITS)
    elif label == 0o241:
        return _bit_fault_summary(word, _CBIT1_BITS)
    elif label == 0o242:
        return _bit_fault_summary(word, _CBIT2_BITS)
    elif label == 0o243:
        return _bit_fault_summary(word, _CBIT3_BITS)
    elif label == 0o137:
        b11 = ARINC429Decoder.extract_data_bits(word, 11, 11)
        b12 = ARINC429Decoder.extract_data_bits(word, 12, 12)
        b13 = ARINC429Decoder.extract_data_bits(word, 13, 13)
        t = "有效" if b11 else "无效"
        c = "有效" if b12 else "无效"
        l = "有效" if b13 else "无效"
        return f"起飞:{t},巡航:{c},着陆:{l}"
    elif label == 0o236:
        return "启动自检" if raw_val == 1 else "不自检"
    elif label == 0o237:
        return _HEAT_CMD_MAP.get(raw_val, f"未知({raw_val})")
    elif label == 0o235:
        b11 = ARINC429Decoder.extract_data_bits(word, 11, 11)
        return "承压" if b11 == 1 else "不承压"
    return str(raw_val)


def _bit_fault_summary(word: int, bit_defs: list) -> str:
    faults = []
    for bit_pos, name in bit_defs:
        if ARINC429Decoder.extract_data_bits(word, bit_pos, bit_pos):
            faults.append(name)
    return "正常" if not faults else "故障:" + ",".join(faults)


# ---------------------------------------------------------------------------
#  解析器主类
# ---------------------------------------------------------------------------

@ParserRegistry.register
class ADCParser(Arinc429Mixin, BaseParser):
    """S/ADS-5 大气数据系统解析器 (adc_v2.2)"""

    parser_key = "adc_v2.2"
    name = "大气数据系统"
    supported_ports: List[int] = [7001, 7002, 7003, 7022, 7023, 7024, 7025, 7026, 7027]

    _LABEL_DEFS = _LABEL_DEFS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL
    _OUTPUT_COLUMNS = _OUTPUT_COLUMNS
    _PORT_LABELS = _PORT_LABELS

    OUTPUT_COLUMNS = _OUTPUT_COLUMNS

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    def _common_columns(self) -> List[str]:
        return ["timestamp", "adru_id", "adru_id_cn"]

    def _columns_for_label(self, label: int) -> List[str]:
        return _columns_for_label(label)

    # ------------------------------------------------------------------
    # 解码逻辑（ADC 专有）
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        defn = _LABEL_DEFS.get(label)
        if defn is None:
            return

        pfx = label_prefix(label)
        col = defn["col"]
        enc = defn["enc"]

        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)
        parity = parity_ok(word)

        record["adru_id"] = sdi
        record["adru_id_cn"] = _ADRU_ID_MAP.get(sdi, f"SDI={sdi}")

        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = _SSM_TEXT.get(ssm, str(ssm))
        record[f"{pfx}.parity"] = parity

        if enc == "bnr":
            value = self.decoder.decode_bnr_with_lsb(
                word,
                msb_bit=defn["msb_bit"],
                lsb_bit=defn["lsb_bit"],
                lsb_value=defn["lsb_val"],
                signed=defn.get("signed", True),
            )
            record[f"{pfx}.{col}"] = round(value, 8)

        elif enc == "discrete":
            lo, hi = defn["bits"]
            raw = ARINC429Decoder.extract_data_bits(word, lo, hi)
            record[f"{pfx}.{col}"] = raw
            record[f"{pfx}.{col}_enum"] = _discrete_enum(label, word, raw)

        elif enc == "bcd_pressure":
            val = _decode_bcd_pressure(word)
            record[f"{pfx}.{col}"] = val
            record[f"{pfx}.{col}_enum"] = f"{val} hPa" if val is not None else "无效"

        elif enc == "bcd_version":
            raw_int = ARINC429Decoder.extract_data_bits(word, 11, 28)
            ver_str = _decode_bcd_sw_version(word)
            record[f"{pfx}.{col}"] = raw_int
            record[f"{pfx}.{col}_enum"] = ver_str
