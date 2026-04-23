# -*- coding: utf-8 -*-
"""
电起落架收放控制单元 (LGCU) 解析器（bundle-only）

实现依据：
- 电起落架收放控制单元EOICD_V4.0.doc

SDI 区分 LGCU1 / LGCU2：
- LGCU1: SDI = 01
- LGCU2: SDI = 10

LGCU 全部字段都是单 bit 离散量，由 DeviceBundle.discrete_bits 承载；parser
只负责声明 label 集合、设备级 unit_id 以及转调 _decode_with_bundle。
"""
from typing import Any, Dict, List, Optional

from .base import BaseParser, ParserRegistry
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


_LABEL_INTS = (
    # 上行 (LGCU → 飞管)
    0o103, 0o115, 0o271, 0o273, 0o274, 0o275, 0o276,
    0o350, 0o351, 0o354, 0o355, 0o360, 0o361, 0o364, 0o367,
    # 下行 (FCC → LGCU)
    0o305, 0o306, 0o307, 0o310,
)

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_INTS)


@ParserRegistry.register
class LGCUParser(Arinc429Mixin, BaseParser):
    parser_key = "lgcu_v4.0"
    name = "电起落架收放控制单元"
    supported_ports: List[int] = [7077, 7078, 7079, 7080, 8021, 8022, 8023, 8024]

    _LABEL_INTS = _LABEL_INTS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        return port in self.supported_ports if self.supported_ports else False

    def _common_columns(self) -> List[str]:
        return ["timestamp", "unit_id", "unit_id_cn"]

    def _ssm_text(self, ssm: int) -> str:
        return _SSM_TEXT.get(int(ssm), str(ssm))

    def _write_device_id(self, record: Dict[str, Any], sdi: int) -> None:
        record["unit_id"] = sdi
        record["unit_id_cn"] = _SDI_UNIT_TEXT.get(sdi, f"SDI={sdi}")

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
