# -*- coding: utf-8 -*-
"""
机轮刹车系统 (Brake/BCMU/ABCU) 解析器

实现依据：
- 【最新版】机轮刹车系统EIOCD字节定义_V7.3—修正了字节的1、0定义.docx

SDI 区分 ABCU / BCMU：
- bit10=1, bit9=0 → ABCU
- bit10=0, bit9=1 → BCMU

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
    0: "故障",
    1: "无效",
    2: "测试",
    3: "正常",
}

_SDI_UNIT_TEXT = {
    0b10: "ABCU",
    0b01: "BCMU",
}

_FCC_MASTER_TEXT = {
    0b00: "飞控1为主",
    0b01: "飞控2为主",
    0b10: "飞控3为主",
    0b11: "飞控4为主",
}

_LABEL_DEFS: Dict[int, Dict[str, Any]] = {
    # 轮速 (km/h, 0-510, res=2)
    0o004: {"col": "left_inside_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "左内主轮速"},
    0o005: {"col": "left_outside_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "左外主轮速"},
    0o006: {"col": "right_inside_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "右内主轮速"},
    0o007: {"col": "right_outside_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "右外主轮速"},
    0o002: {"col": "left_avg_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "左起落架平均轮速"},
    0o003: {"col": "right_avg_wheel_speed", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 2.0, "signed": False, "unit": "km/h", "cn": "右起落架平均轮速"},
    # 胎压 (psi, 0-655.35, res=0.01)
    0o060: {"col": "left_inside_tire_pressure", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 0.01, "signed": False, "unit": "psi", "cn": "左内胎压"},
    0o062: {"col": "left_outside_tire_pressure", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 0.01, "signed": False, "unit": "psi", "cn": "左外胎压"},
    0o061: {"col": "right_inside_tire_pressure", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 0.01, "signed": False, "unit": "psi", "cn": "右内胎压"},
    0o063: {"col": "right_outside_tire_pressure", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 0.01, "signed": False, "unit": "psi", "cn": "右外胎压"},
    # 刹车压力 (N, 0-65536, res=1)
    0o070: {"col": "left_inside_brake_force", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 1.0, "signed": False, "unit": "N", "cn": "左内刹车压力"},
    0o072: {"col": "left_outside_brake_force", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 1.0, "signed": False, "unit": "N", "cn": "左外刹车压力"},
    0o071: {"col": "right_inside_brake_force", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 1.0, "signed": False, "unit": "N", "cn": "右内刹车压力"},
    0o073: {"col": "right_outside_brake_force", "enc": "bnr", "lsb_bit": 11, "msb_bit": 26, "lsb_val": 1.0, "signed": False, "unit": "N", "cn": "右外刹车压力"},
    # 刹车温度 (℃, 0-2560, res=10)
    0o114: {"col": "left_inside_brake_temp", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 10.0, "signed": False, "unit": "℃", "cn": "左内刹车温度"},
    0o116: {"col": "left_outside_brake_temp", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 10.0, "signed": False, "unit": "℃", "cn": "左外刹车温度"},
    0o115: {"col": "right_inside_brake_temp", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 10.0, "signed": False, "unit": "℃", "cn": "右内刹车温度"},
    0o117: {"col": "right_outside_brake_temp", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 10.0, "signed": False, "unit": "℃", "cn": "右外刹车温度"},
    # 脚蹬行程 (%, 0-256, res=1)
    0o170: {"col": "left_main_pedal_stroke", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "左主脚蹬行程"},
    0o172: {"col": "left_copilot_pedal_stroke", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "左副脚蹬行程"},
    0o171: {"col": "right_main_pedal_stroke", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "右主脚蹬行程"},
    0o173: {"col": "right_copilot_pedal_stroke", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "右副脚蹬行程"},
    # 刹车量反馈 (%, 0-256, res=1)
    0o174: {"col": "left_brake_feedback", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "左刹车量反馈"},
    0o175: {"col": "right_brake_feedback", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "右刹车量反馈"},
    # 自动飞行刹车回绕 (%, 0-256, res=1)
    0o176: {"col": "autoflight_left_brake_cmd", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "自动飞行左刹车回绕"},
    0o177: {"col": "autoflight_right_brake_cmd", "enc": "bnr", "lsb_bit": 11, "msb_bit": 18, "lsb_val": 1.0, "signed": False, "unit": "%", "cn": "自动飞行右刹车回绕"},
    # 离散 Label
    0o351: {"col": "cas1", "enc": "discrete_351"},
    0o051: {"col": "cas2", "enc": "discrete_051"},
    0o352: {"col": "antiskid_brk_mode", "enc": "discrete_352"},
    0o353: {"col": "autoflight_echo", "enc": "discrete_353"},
}

_ALL_LABELS = sorted(_LABEL_DEFS.keys())

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)


def _yn(v: int) -> str:
    return "有效" if v == 1 else "无效"


def _columns_for_label(label: int) -> List[str]:
    pfx = label_prefix(label)
    defn = _LABEL_DEFS[label]
    cols: List[str] = []

    enc = defn["enc"]
    if enc == "bnr":
        cols.append(f"{pfx}.{defn['col']}")
    elif enc == "discrete_351":
        for field in [
            "park_brk_fail", "park_brk_on", "park_brk_apply",
            "brk_nml_fail", "antiskid_off", "brk_emer_fail",
            "brk_total_loss", "brk_degrd", "brk_lh_fail", "brk_rh_fail",
            "antiskid_fail",
            "left_inside_temp_overheat", "left_outside_temp_overheat",
            "right_inside_temp_overheat", "right_outside_temp_overheat",
            "brk_temp_fail",
        ]:
            cols.append(f"{pfx}.{field}")
    elif enc == "discrete_051":
        for field in [
            "auto_brk_fail", "auto_brk_lo", "auto_brk_med",
            "auto_brk_hi", "auto_brk_rto", "brk_plt_ped_fail",
            "brk_coplt_ped_fail", "brk_nml_no_dispatch",
            "tire_pr_fail",
            "left_inside_tire_pr_advy", "left_outside_tire_pr_advy",
            "right_inside_tire_pr_advy", "right_outside_tire_pr_advy",
            "ctr_status",
        ]:
            cols.append(f"{pfx}.{field}")
    elif enc == "discrete_352":
        for field in [
            "left_inside_antiskid", "left_outside_antiskid",
            "right_inside_antiskid", "right_outside_antiskid",
            "left_inside_antiskid_fault", "left_outside_antiskid_fault",
            "right_inside_antiskid_fault", "right_outside_antiskid_fault",
            "auto_brk_on", "brk_nml_on", "brk_alt_on", "brk_emer_on",
        ]:
            cols.append(f"{pfx}.{field}")
    elif enc == "discrete_353":
        for field in [
            "fcc_master", "fcc_master_enum",
            "autoflight_mode_on", "autoflight_park_brake_on",
            "autoflight_antiskid_on",
            "autoflight_autobrake_off", "autoflight_autobrake_lo",
            "autoflight_autobrake_med", "autoflight_autobrake_hi",
            "autoflight_autobrake_rto",
            "left_throttle_cmd", "right_throttle_cmd",
        ]:
            cols.append(f"{pfx}.{field}")

    cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
    return cols


def _build_output_columns() -> List[str]:
    cols = ["timestamp", "unit_id", "unit_id_cn"]
    for label in _ALL_LABELS:
        cols.extend(_columns_for_label(label))
    return cols


_OUTPUT_COLUMNS = _build_output_columns()


@ParserRegistry.register
class BrakeParser(Arinc429Mixin, BaseParser):
    parser_key = "brake_v7.3"
    name = "机轮刹车系统"
    supported_ports: List[int] = [7087, 7088, 7089, 7090]

    _LABEL_DEFS = _LABEL_DEFS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL
    _OUTPUT_COLUMNS = _OUTPUT_COLUMNS
    _PORT_LABELS = None

    OUTPUT_COLUMNS = _OUTPUT_COLUMNS

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        return port in self.supported_ports if self.supported_ports else False

    def _common_columns(self) -> List[str]:
        return ["timestamp", "unit_id", "unit_id_cn"]

    def _columns_for_label(self, label: int) -> List[str]:
        return _columns_for_label(label)

    # ------------------------------------------------------------------
    # 解码逻辑（Brake 专有）
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        defn = _LABEL_DEFS.get(label)
        if defn is None:
            return

        pfx = label_prefix(label)
        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)
        parity = parity_ok(word)

        record["unit_id"] = sdi
        record["unit_id_cn"] = _SDI_UNIT_TEXT.get(sdi, f"SDI={sdi}")
        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = _SSM_TEXT.get(ssm, str(ssm))
        record[f"{pfx}.parity"] = parity

        enc = defn["enc"]

        if enc == "bnr":
            value = self.decoder.decode_bnr_with_lsb(
                word,
                msb_bit=defn["msb_bit"],
                lsb_bit=defn["lsb_bit"],
                lsb_value=defn["lsb_val"],
                signed=defn.get("signed", False),
            )
            record[f"{pfx}.{defn['col']}"] = round(value, 8)

        elif enc == "discrete_351":
            self._decode_cas1(word, pfx, record)

        elif enc == "discrete_051":
            self._decode_cas2(word, pfx, record)

        elif enc == "discrete_352":
            self._decode_antiskid_mode(word, pfx, record)

        elif enc == "discrete_353":
            self._decode_autoflight_echo(word, pfx, record)

    @staticmethod
    def _decode_cas1(word: int, pfx: str, record: Dict[str, Any]):
        eb = ARINC429Decoder.extract_data_bits
        record[f"{pfx}.park_brk_fail"] = eb(word, 11, 11)
        record[f"{pfx}.park_brk_on"] = eb(word, 12, 12)
        record[f"{pfx}.park_brk_apply"] = eb(word, 13, 13)
        record[f"{pfx}.brk_nml_fail"] = eb(word, 14, 14)
        record[f"{pfx}.antiskid_off"] = eb(word, 15, 15)
        record[f"{pfx}.brk_emer_fail"] = eb(word, 16, 16)
        record[f"{pfx}.brk_total_loss"] = eb(word, 17, 17)
        record[f"{pfx}.brk_degrd"] = eb(word, 18, 18)
        record[f"{pfx}.brk_lh_fail"] = eb(word, 19, 19)
        record[f"{pfx}.brk_rh_fail"] = eb(word, 20, 20)
        record[f"{pfx}.antiskid_fail"] = eb(word, 21, 21)
        record[f"{pfx}.left_inside_temp_overheat"] = eb(word, 22, 22)
        record[f"{pfx}.left_outside_temp_overheat"] = eb(word, 23, 23)
        record[f"{pfx}.right_inside_temp_overheat"] = eb(word, 24, 24)
        record[f"{pfx}.right_outside_temp_overheat"] = eb(word, 25, 25)
        record[f"{pfx}.brk_temp_fail"] = eb(word, 26, 26)

    @staticmethod
    def _decode_cas2(word: int, pfx: str, record: Dict[str, Any]):
        eb = ARINC429Decoder.extract_data_bits
        record[f"{pfx}.auto_brk_fail"] = eb(word, 11, 11)
        record[f"{pfx}.auto_brk_lo"] = eb(word, 12, 12)
        record[f"{pfx}.auto_brk_med"] = eb(word, 13, 13)
        record[f"{pfx}.auto_brk_hi"] = eb(word, 14, 14)
        record[f"{pfx}.auto_brk_rto"] = eb(word, 15, 15)
        record[f"{pfx}.brk_plt_ped_fail"] = eb(word, 16, 16)
        record[f"{pfx}.brk_coplt_ped_fail"] = eb(word, 17, 17)
        record[f"{pfx}.brk_nml_no_dispatch"] = eb(word, 18, 18)
        record[f"{pfx}.tire_pr_fail"] = eb(word, 19, 19)
        record[f"{pfx}.left_inside_tire_pr_advy"] = eb(word, 20, 20)
        record[f"{pfx}.left_outside_tire_pr_advy"] = eb(word, 21, 21)
        record[f"{pfx}.right_inside_tire_pr_advy"] = eb(word, 22, 22)
        record[f"{pfx}.right_outside_tire_pr_advy"] = eb(word, 23, 23)
        record[f"{pfx}.ctr_status"] = eb(word, 24, 24)

    @staticmethod
    def _decode_antiskid_mode(word: int, pfx: str, record: Dict[str, Any]):
        eb = ARINC429Decoder.extract_data_bits
        record[f"{pfx}.left_inside_antiskid"] = eb(word, 11, 11)
        record[f"{pfx}.left_outside_antiskid"] = eb(word, 12, 12)
        record[f"{pfx}.right_inside_antiskid"] = eb(word, 13, 13)
        record[f"{pfx}.right_outside_antiskid"] = eb(word, 14, 14)
        record[f"{pfx}.left_inside_antiskid_fault"] = eb(word, 15, 15)
        record[f"{pfx}.left_outside_antiskid_fault"] = eb(word, 16, 16)
        record[f"{pfx}.right_inside_antiskid_fault"] = eb(word, 17, 17)
        record[f"{pfx}.right_outside_antiskid_fault"] = eb(word, 18, 18)
        record[f"{pfx}.auto_brk_on"] = eb(word, 19, 19)
        record[f"{pfx}.brk_nml_on"] = eb(word, 20, 20)
        record[f"{pfx}.brk_alt_on"] = eb(word, 21, 21)
        record[f"{pfx}.brk_emer_on"] = eb(word, 22, 22)

    @staticmethod
    def _decode_autoflight_echo(word: int, pfx: str, record: Dict[str, Any]):
        eb = ARINC429Decoder.extract_data_bits
        fcc_master = eb(word, 9, 10)
        record[f"{pfx}.fcc_master"] = fcc_master
        record[f"{pfx}.fcc_master_enum"] = _FCC_MASTER_TEXT.get(fcc_master, f"未知({fcc_master})")
        record[f"{pfx}.autoflight_mode_on"] = eb(word, 11, 11)
        record[f"{pfx}.autoflight_park_brake_on"] = eb(word, 12, 12)
        record[f"{pfx}.autoflight_antiskid_on"] = eb(word, 13, 13)
        record[f"{pfx}.autoflight_autobrake_off"] = eb(word, 14, 14)
        record[f"{pfx}.autoflight_autobrake_lo"] = eb(word, 15, 15)
        record[f"{pfx}.autoflight_autobrake_med"] = eb(word, 16, 16)
        record[f"{pfx}.autoflight_autobrake_hi"] = eb(word, 17, 17)
        record[f"{pfx}.autoflight_autobrake_rto"] = eb(word, 18, 18)
        record[f"{pfx}.left_throttle_cmd"] = eb(word, 19, 19)
        record[f"{pfx}.right_throttle_cmd"] = eb(word, 20, 20)
