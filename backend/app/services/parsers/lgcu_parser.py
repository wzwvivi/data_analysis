# -*- coding: utf-8 -*-
"""
电起落架收放控制单元 (LGCU) 解析器

实现依据：
- 电起落架收放控制单元EOICD_V4.0.doc

SDI 区分 LGCU1 / LGCU2：
- LGCU1 控制通道: SDI = 01
- LGCU2 控制通道: SDI = 10
- LGCU1 监控通道: SDI = 01
- LGCU2 监控通道: SDI = 10

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
    0b01: "LGCU1",
    0b10: "LGCU2",
}

_LABEL_DEFS: Dict[int, Dict[str, Any]] = {
    0o103: {"col": "lg_prox_lgcu1_mon", "enc": "discrete_103"},
    0o115: {"col": "lg_prox_lgcu2_mon", "enc": "discrete_115"},
    0o271: {"col": "lg_position_sensors", "enc": "discrete_271"},
    0o273: {"col": "consolidated_lg_pos", "enc": "discrete_273"},
    0o274: {"col": "woffw_data", "enc": "discrete_274"},
    0o275: {"col": "consolidated_wow", "enc": "discrete_275"},
    0o276: {"col": "lg_pos_indication", "enc": "discrete_276"},
    0o350: {"col": "maint_word1", "enc": "discrete_350"},
    0o351: {"col": "maint_word2", "enc": "discrete_351"},
    0o354: {"col": "maint_word5", "enc": "discrete_354"},
    0o355: {"col": "maint_word6", "enc": "discrete_355"},
    0o360: {"col": "maint_word8", "enc": "discrete_360"},
    0o361: {"col": "maint_word9", "enc": "discrete_361"},
    0o364: {"col": "maint_word12", "enc": "discrete_364"},
    0o367: {"col": "maint_word13", "enc": "discrete_367"},
}

_ALL_LABELS = sorted(_LABEL_DEFS.keys())

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_DEFS)

# ── 每个 Label 的离散位字段名列表 ──

_DISCRETE_FIELDS: Dict[int, List[str]] = {
    0o103: [
        "rh_mlg_woffw_1", "rh_mlg_woffw_1_op",
        "spare_13", "spare_14",
        "rh_mlg_dnlk_1", "rh_mlg_dnlk_1_op",
    ],
    0o115: [
        "lh_mlg_woffw_2", "lh_mlg_woffw_2_op",
        "spare_13", "spare_14",
        "lh_mlg_dnlk_2", "lh_mlg_dnlk_2_op",
    ],
    0o271: [
        "mlg_rh_uplock", "mlg_lh_uplock", "nlg_lock",
        "mlg_rh_dnlock", "mlg_lh_dnlock", "nlg_pos",
        "mlg_rh_uplock_op", "mlg_lh_uplock_op", "nlg_lock_op",
        "mlg_rh_dnlock_op", "mlg_lh_dnlock_op", "nlg_pos_op",
        "lgcl_up", "lgcl_down", "lgcl_up_op", "lgcl_down_op",
        "lgcl_auto", "lgcl_auto_op",
    ],
    0o273: [
        "all_gear_dnlk", "all_gear_uplk",
        "nlg_uplk", "nlg_dnlk",
        "cmd_retract", "cmd_extend",
        "auto_retract_cmd", "auto_extend_cmd", "auto_flight_mode",
        "spare_20", "spare_21", "spare_22", "spare_23",
        "lgcl_up_dn", "spare_25", "spare_26",
        "cons_mlg_dnlk", "cons_mlg_uplk", "lgcl_dn_up",
    ],
    0o274: [
        "rh_mlg_wow", "lh_mlg_wow", "nlg_wow",
        "rh_mlg_wow_op", "lh_mlg_wow_op", "nlg_wow_op",
    ],
    0o275: [
        "spare_11",
        "all_gear_wow", "mlg_wow", "gr_woffw", "nlg_wow",
        "nlg_uplock_sw_off_mon", "rh_mlg_uplock_sw_off_mon",
        "lh_mlg_uplock_sw_off_mon",
        "spare_19", "spare_20", "spare_21", "spare_22",
        "aes_gnd_disc", "aes_28v_en",
        "all_gear_wow_op", "mlg_wow_op",
    ],
    0o276: [
        "lg_sys_nd_fault", "lgcu_internal_fault", "lg_sys_degraded",
        "wow_sys_fault", "wow_sys_degraded",
        "alt_ext_lg_down", "alt_ext_lg_fault",
        "ng_disagree", "lg_disagree", "rg_disagree",
        "ng_uplocked", "lg_uplocked", "rg_uplocked",
        "ng_in_transit", "lg_in_transit", "rg_in_transit",
        "ng_downlocked", "lg_downlocked", "rg_downlocked",
    ],
    0o350: [
        "lgcu_nd_fault", "aes_relay3_nd_fault", "aes_relay3_elec_fault",
        "aes_relay2_nd_fault", "aes_relay1_elec_fault",
        "aes_relay2_elec_fault",
        "aes_ng_uplk_elec_fault", "aes_lg_uplk_elec_fault",
        "aes_rg_uplk_elec_fault",
        "spare_20", "spare_21",
        "ehm3_fault", "lgcl_elec_fault", "lgcl_nd_fault",
        "aev_pos2_elec_fault", "ehm1_fault", "ehm2_fault",
        "aev_pos1_elec_fault", "aes_relay1_nd_fault",
    ],
    0o351: [
        "lh_mlg_woffw_adj", "rh_mlg_woffw_adj", "nlg_woffw_adj",
        "lh_mlg_dnlock_adj", "rh_mlg_dnlock_adj", "nlg_dnlock_adj",
        "nlg_uplock_adj", "rh_mlg_uplock_adj", "lh_mlg_uplock_adj",
    ],
    0o354: [
        "spare_11", "spare_12",
        "aes_relay4_nd_fault", "aes_relay4_elec_fault",
        "aes_relay5_nd_fault", "aes_relay5_elec_fault",
    ],
    0o355: [
        "invalid_time_date",
        "spare_12", "spare_13", "spare_14", "spare_15",
        "spare_16", "spare_17", "spare_18", "spare_19",
        "spare_20", "spare_21", "spare_22", "spare_23", "spare_24",
        "invalid_crosscom_cc",
        "spare_26", "spare_27",
    ],
    0o360: [
        "lh_mlg_woffw_unreas", "rh_mlg_woffw_unreas", "nlg_woffw_unreas",
        "lh_mlg_dnlock_unreas", "rh_mlg_dnlock_unreas", "nlg_dnlock_unreas",
        "nlg_uplock_unreas", "rh_mlg_uplock_unreas", "lh_mlg_uplock_unreas",
    ],
    0o361: [
        "lh_mlg_woffw_fault", "rh_mlg_woffw_fault", "nlg_woffw_fault",
        "lh_mlg_dnlock_fault", "rh_mlg_dnlock_fault", "nlg_dnlock_fault",
        "nlg_uplock_fault", "rh_mlg_uplock_fault", "lh_mlg_uplock_fault",
        "spare_20",
        "do_cons_mlg_wow_fault", "do_mlg_lh_wow_fault",
        "do_mlg_rh_wow_fault",
        "do_cons_mlg_uplk_fault", "do_cons_mlg_not_dnlk_fault",
        "dc_bus_low",
        "spare_27",
        "ae_valve_mech_fault", "dc_ess_bus_low",
    ],
    0o364: [
        "mc_adc_bit_flt", "cc_adc_bit_flt",
        "dac_bit_flt",
        "spare_14", "spare_15", "spare_16",
        "aev_do_pos2_mon_flt",
        "mc_sw_inop_mon_flt", "cc_sw_inop_mon_flt",
        "pow_int_eval_flt", "aev_do_pos1_mon_flt",
        "ext_do_mon_flt", "cmd_asym_mon_flt",
        "internal_bus_flt", "eeprom_calib_flt",
        "mc_timing_test_flt", "dr_open_do_mon_flt",
        "dr_cld_do_mon_flt", "ret_do_mon_flt",
    ],
    0o367: [
        "spare_11", "spare_12",
        "aev2_28v_pos1", "aev2_28v_pos2",
        "lgcl_aes_28v_en",
        "spare_16",
        "rh_mlg_uplock_gnd", "lh_mlg_uplock_gnd", "nlg_uplock_gnd",
        "spare_20", "spare_21", "spare_22", "spare_23",
        "rh_mlg_uplock_28v", "lh_mlg_uplock_28v", "nlg_uplock_28v",
    ],
}

_DISCRETE_START_BIT: Dict[int, int] = {k: 11 for k in _LABEL_DEFS}


def _columns_for_label(label: int) -> List[str]:
    pfx = label_prefix(label)
    cols: List[str] = []
    fields = _DISCRETE_FIELDS.get(label, [])
    for f in fields:
        cols.append(f"{pfx}.{f}")
    cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
    return cols


def _build_output_columns() -> List[str]:
    cols = ["timestamp", "unit_id", "unit_id_cn"]
    for label in _ALL_LABELS:
        cols.extend(_columns_for_label(label))
    return cols


_OUTPUT_COLUMNS = _build_output_columns()


@ParserRegistry.register
class LGCUParser(Arinc429Mixin, BaseParser):
    parser_key = "lgcu_v4.0"
    name = "电起落架收放控制单元"
    supported_ports: List[int] = [7077, 7078, 7079, 7080]

    _LABEL_DEFS = _LABEL_DEFS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL
    _OUTPUT_COLUMNS = _OUTPUT_COLUMNS
    _PORT_LABELS = {
        # 按 ICD：7077/7079 为收放状态与维护字；7078 为 L103；7080 为 L115
        7077: [0o271, 0o273, 0o274, 0o275, 0o276, 0o350, 0o351, 0o354, 0o355, 0o360, 0o361, 0o364, 0o367],
        7078: [0o103],
        7079: [0o271, 0o273, 0o274, 0o275, 0o276, 0o350, 0o351, 0o354, 0o355, 0o360, 0o361, 0o364, 0o367],
        7080: [0o115],
    }

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
    # 解码逻辑（LGCU 专有 - 全部为离散位）
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        defn = _LABEL_DEFS.get(label)
        if defn is None:
            return

        pfx = label_prefix(label)
        sdi = self.decoder.extract_sdi(word)
        ssm = self.decoder.extract_ssm(word)

        record["unit_id"] = sdi
        record["unit_id_cn"] = _SDI_UNIT_TEXT.get(sdi, f"SDI={sdi}")
        record[f"{pfx}.sdi"] = sdi
        record[f"{pfx}.ssm"] = ssm
        record[f"{pfx}.ssm_enum"] = _SSM_TEXT.get(ssm, str(ssm))
        record[f"{pfx}.parity"] = parity_ok(word)

        fields = _DISCRETE_FIELDS.get(label, [])
        start_bit = _DISCRETE_START_BIT.get(label, 11)
        eb = ARINC429Decoder.extract_data_bits
        for i, fname in enumerate(fields):
            bit_pos = start_bit + i
            record[f"{pfx}.{fname}"] = eb(word, bit_pos, bit_pos)
