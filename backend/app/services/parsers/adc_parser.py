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
"""
import struct
from typing import Dict, List, Any, Optional

from .base import BaseParser, ParserRegistry, FieldLayout
from .arinc429 import ARINC429Decoder

TSN_HEADER_LEN = 8

_SSM_TEXT = {0: "故障告警", 1: "无计算数据", 2: "功能测试", 3: "正常数据"}

# ---------------------------------------------------------------------------
#  ARINC 429 Label 定义表（数据驱动）
#  key = 八进制 label 值
#  encoding: bnr / discrete / bcd_pressure / bcd_version
#  对于 bnr: lsb_bit/msb_bit 为协议中的"数据格式"位号（1-32），lsb_val 为分辨率
# ---------------------------------------------------------------------------

_LABEL_DEFS: Dict[int, dict] = {
    # ====== A. 表决后 BNR (ADRU → FCC + DIU) ======
    0o203: {"col": "abs_alt_voted_ft",       "cn": "绝对气压高度(表决后)",   "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o103: {"col": "qnh_alt_voted_ft",       "cn": "相对气压高度QNH(表决后)","enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o102: {"col": "qfe_alt_voted_ft",       "cn": "相对气压高度QFE(表决后)","enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o205: {"col": "mach_voted",             "cn": "马赫数(表决后)",         "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.0000625,  "signed": True,  "unit": ""},
    0o206: {"col": "ias_voted_kn",           "cn": "指示空速(表决后)",       "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o207: {"col": "cas_voted_kn",           "cn": "校准空速(表决后)",       "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o210: {"col": "tas_voted_kn",           "cn": "真空速(表决后)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o212: {"col": "vspeed_voted_ftmin",     "cn": "升降速度(表决后)",       "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 3.0,       "signed": True,  "unit": "ft/min"},
    0o211: {"col": "tat_voted_c",            "cn": "总温(表决后)",           "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o213: {"col": "sat_voted_c",            "cn": "静温(表决后)",           "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o221: {"col": "aoa_voted_deg",          "cn": "迎角(表决后)",           "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},
    0o226: {"col": "aos_voted_deg",          "cn": "侧滑角(表决后)",         "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},

    # ====== B. 源数据 BNR (ADRU → DIU) ======
    0o176: {"col": "left_sp_raw_hpa",        "cn": "未修正左静压",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o177: {"col": "right_sp_raw_hpa",       "cn": "未修正右静压",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o244: {"col": "total_p_raw_hpa",        "cn": "总压(源数据)",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o245: {"col": "avg_sp_raw_hpa",         "cn": "未修正平均静压",         "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o246: {"col": "avg_sp_corr_hpa",        "cn": "修正平均静压",           "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.03125,   "signed": True,  "unit": "hPa"},
    0o303: {"col": "abs_alt_src_ft",         "cn": "绝对气压高度(源数据)",   "enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o304: {"col": "qnh_alt_src_ft",         "cn": "相对气压高度QNH(源数据)","enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o314: {"col": "qfe_alt_src_ft",         "cn": "相对气压高度QFE(源数据)","enc": "bnr", "lsb_bit": 12, "msb_bit": 28, "lsb_val": 0.25,      "signed": True,  "unit": "ft"},
    0o305: {"col": "mach_src",               "cn": "马赫数(源数据)",         "enc": "bnr", "lsb_bit": 13, "msb_bit": 28, "lsb_val": 0.0000625,  "signed": True,  "unit": ""},
    0o306: {"col": "ias_src_kn",             "cn": "指示空速(源数据)",       "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o307: {"col": "cas_src_kn",             "cn": "校准空速(源数据)",       "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o310: {"col": "tas_src_kn",             "cn": "真空速(源数据)",         "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.125,     "signed": True,  "unit": "kn"},
    0o312: {"col": "vspeed_src_ftmin",       "cn": "升降速度(源数据)",       "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 3.0,       "signed": True,  "unit": "ft/min"},
    0o311: {"col": "tat_src_c",              "cn": "总温(源数据)",           "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o313: {"col": "sat_src_c",              "cn": "静温(源数据)",           "enc": "bnr", "lsb_bit": 18, "msb_bit": 28, "lsb_val": 0.0625,    "signed": True,  "unit": "℃"},
    0o321: {"col": "aoa_src_deg",            "cn": "迎角(源数据)",           "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},
    0o326: {"col": "aos_src_deg",            "cn": "侧滑角(源数据)",         "enc": "bnr", "lsb_bit": 17, "msb_bit": 28, "lsb_val": 0.05,      "signed": True,  "unit": "°"},

    # ====== C1. 自检状态字 (离散量，100ms) ======
    0o240: {"col": "pbit_240",               "cn": "上电自检状态字",         "enc": "discrete", "bits": (11, 19)},
    0o241: {"col": "cbit_241",               "cn": "周期自检状态字1",        "enc": "discrete", "bits": (11, 29)},
    0o242: {"col": "cbit_242",               "cn": "周期自检状态字2",        "enc": "discrete", "bits": (11, 29)},
    0o243: {"col": "cbit_243",               "cn": "周期自检状态字3",        "enc": "discrete", "bits": (11, 23)},

    # ====== C2. 软件版本 (BCD, 1000ms) ======
    0o350: {"col": "sw_version",             "cn": "软件版本",               "enc": "bcd_version"},

    # ====== C3. 回报参数 (ADRU → DIU) ======
    0o233: {"col": "qnh_report_hpa",         "cn": "装订气压QNH回报",        "enc": "bcd_pressure"},
    0o234: {"col": "qfe_report_hpa",         "cn": "装订气压QFE回报",        "enc": "bcd_pressure"},
    0o137: {"col": "flap_status_report",     "cn": "襟翼状态回报",           "enc": "discrete", "bits": (11, 13)},
    0o364: {"col": "inertial_vrate_report",  "cn": "惯性垂直速率回报",       "enc": "bnr", "lsb_bit": 15, "msb_bit": 28, "lsb_val": 0.01, "signed": True, "unit": "m/s²"},
    0o236: {"col": "maint_bit_cmd_report",   "cn": "维护自检指令回报",       "enc": "discrete", "bits": (11, 11)},
    0o237: {"col": "heat_cmd_report",        "cn": "强制加温指令回报",       "enc": "discrete", "bits": (11, 12)},
    0o235: {"col": "wow_report",             "cn": "轮载信号回报",           "enc": "discrete", "bits": (11, 12)},
}

# 已知 Label 的八进制值集合
_KNOWN_LABELS = set(_LABEL_DEFS.keys())

# 所有可能的输出列
_OUTPUT_COLUMNS = (
    [
        "timestamp",
        "adru_id",
        "adru_id_cn",
        # 首个命中的label信息（兼容旧字段）
        "label_octal",
        "label_name",
        "ssm",
        "ssm_cn",
        # 包级聚合信息（避免单包多label时元信息被覆盖误解）
        "label_count",
        "labels_octal",
        "labels_cn",
        "ssm_values",
    ]
    + [d["col"] for d in _LABEL_DEFS.values()]
    + [
        # 关键离散量语义化拆解字段
        "flap_takeoff_valid",
        "flap_cruise_valid",
        "flap_landing_valid",
        "maint_bit_cmd_active",
        "maint_bit_cmd_cn",
        "heat_cmd_mode",
        "heat_cmd_mode_cn",
        "wow_compressed",
        "wow_compressed_cn",
    ]
)


# ---------------------------------------------------------------------------
#  BCD 气压解码（装订气压 QNH/QFE）
#  协议格式 bit11=LSB(十分位), bit12-14=十分位剩余+MSB(十分位),
#  bit15-18=个位, bit19-22=十位, bit23-26=百位, bit27-29=千位
# ---------------------------------------------------------------------------

def _decode_bcd_pressure(word: int) -> Optional[float]:
    """解码 BCD 气压值（Label 233/234），返回 hPa"""
    d = ARINC429Decoder.extract_data_bits
    tenths  = d(word, 11, 14)  # 十分位 4-bit BCD
    ones    = d(word, 15, 18)  # 个位
    tens    = d(word, 19, 22)  # 十位
    hundreds = d(word, 23, 26) # 百位
    thousands = d(word, 27, 29) & 0x07  # 千位 3-bit BCD (0 or 1)
    if any(v > 9 for v in (tenths, ones, tens, hundreds)):
        return None
    return thousands * 1000 + hundreds * 100 + tens * 10 + ones + tenths * 0.1


def _decode_bcd_sw_version(word: int) -> Optional[str]:
    """
    解码 BCD 软件版本（Label 350）
    协议：bit11=LSB(百分位), bit12-13=百分位剩余+MSB(百分位),
    bit14=MSB(百分位), bit15=LSB(十分位)...
    简化为：直接提取 bit11-22 的 3 个 BCD digit
    """
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
#  ADRU 位置代码（SDI bit9-10）
# ---------------------------------------------------------------------------

_ADRU_ID_MAP = {0: "ADRU#1", 1: "ADRU#2", 2: "ADRU#3", 3: "ADRU#?"}
_HEAT_CMD_MAP = {
    0: "强制不加温",
    1: "强制加温",
    2: "ADRU自动控制加温",
    3: "保留/未定义",
}


# ---------------------------------------------------------------------------
#  解析器主类
# ---------------------------------------------------------------------------

@ParserRegistry.register
class ADCParser(BaseParser):
    """S/ADS-5 大气数据系统解析器 (adc_v2.2)"""

    parser_key = "adc_v2.2"
    name = "大气数据系统"
    supported_ports: List[int] = []

    OUTPUT_COLUMNS = _OUTPUT_COLUMNS

    def __init__(self):
        self.decoder = ARINC429Decoder()

    def can_parse_port(self, port: int) -> bool:
        if not self.supported_ports:
            return True
        return port in self.supported_ports

    # ------------------------------------------------------------------
    def get_output_columns(self, port: int) -> List[str]:
        return list(_OUTPUT_COLUMNS)

    # ------------------------------------------------------------------
    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if len(payload) < TSN_HEADER_LEN + 4:
            return None

        data = payload[TSN_HEADER_LEN:]
        record: Dict[str, Any] = {c: None for c in _OUTPUT_COLUMNS}
        record["timestamp"] = timestamp

        found_any = False
        labels_seen: List[int] = []
        label_names_seen: List[str] = []
        ssm_seen: List[int] = []

        offset = 0
        while offset + 4 <= len(data):
            word = struct.unpack('<I', data[offset:offset + 4])[0]
            offset += 4

            if word == 0:
                continue

            label = self.decoder.extract_label(word)
            defn = _LABEL_DEFS.get(label)
            if defn is None:
                continue

            found_any = True
            col = defn["col"]
            enc = defn["enc"]

            sdi = self.decoder.extract_sdi(word)
            ssm = self.decoder.extract_ssm(word)
            record["adru_id"] = sdi
            record["adru_id_cn"] = _ADRU_ID_MAP.get(sdi, f"SDI={sdi}")
            # 兼容历史字段：仅记录首个命中的label/ssm
            if record["label_octal"] is None:
                record["label_octal"] = oct(label)[2:].zfill(3)
                record["label_name"] = defn["cn"]
                record["ssm"] = ssm
                record["ssm_cn"] = _SSM_TEXT.get(ssm, str(ssm))

            if label not in labels_seen:
                labels_seen.append(label)
                label_names_seen.append(defn["cn"])
            if ssm not in ssm_seen:
                ssm_seen.append(ssm)

            if enc == "bnr":
                value = self.decoder.decode_bnr_with_lsb(
                    word,
                    msb_bit=defn["msb_bit"],
                    lsb_bit=defn["lsb_bit"],
                    lsb_value=defn["lsb_val"],
                    signed=defn.get("signed", True),
                )
                record[col] = round(value, 8)

            elif enc == "discrete":
                lo, hi = defn["bits"]
                raw = ARINC429Decoder.extract_data_bits(word, lo, hi)
                record[col] = raw

                # 对业务常用离散量进行语义化拆解，便于前端直接展示
                if label == 0o137:
                    # bit11: 起飞构型有效, bit12: 常规构型有效, bit13: 着陆构型有效
                    record["flap_takeoff_valid"] = ARINC429Decoder.extract_data_bits(word, 11, 11)
                    record["flap_cruise_valid"] = ARINC429Decoder.extract_data_bits(word, 12, 12)
                    record["flap_landing_valid"] = ARINC429Decoder.extract_data_bits(word, 13, 13)
                elif label == 0o236:
                    active = ARINC429Decoder.extract_data_bits(word, 11, 11)
                    record["maint_bit_cmd_active"] = active
                    record["maint_bit_cmd_cn"] = "启动自检" if active == 1 else "不自检"
                elif label == 0o237:
                    mode = ARINC429Decoder.extract_data_bits(word, 11, 12)
                    record["heat_cmd_mode"] = mode
                    record["heat_cmd_mode_cn"] = _HEAT_CMD_MAP.get(mode, "未知")
                elif label == 0o235:
                    wow = ARINC429Decoder.extract_data_bits(word, 11, 11)
                    record["wow_compressed"] = wow
                    record["wow_compressed_cn"] = "承压" if wow == 1 else "不承压"

            elif enc == "bcd_pressure":
                record[col] = _decode_bcd_pressure(word)

            elif enc == "bcd_version":
                record[col] = _decode_bcd_sw_version(word)

        if not found_any:
            return None

        record["label_count"] = len(labels_seen)
        record["labels_octal"] = ",".join(oct(v)[2:].zfill(3) for v in labels_seen)
        record["labels_cn"] = ";".join(label_names_seen)
        record["ssm_values"] = ",".join(str(v) for v in sorted(ssm_seen))

        return record
