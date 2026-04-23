# -*- coding: utf-8 -*-
"""
机轮刹车系统 (Brake/BCMU/ABCU) 解析器（bundle-only）

实现依据：
- 【最新版】机轮刹车系统EIOCD字节定义_V7.3—修正了字节的1、0定义.docx

SDI 区分 ABCU / BCMU：
- bit10=1, bit9=0 → ABCU
- bit10=0, bit9=1 → BCMU

所有 label 字段定义（bits / 编码 / 单位 / port override）均由 DeviceBundle
承载；本 parser 只负责：
  - 声明可处理的 label 集合（_LABEL_INTS）
  - 设备级 unit_id 映射
  - L353 的 fcc_master 文本映射（parser 侧聚合）
"""
from typing import Any, Dict, List, Optional

from .base import BaseParser, FieldLayout, ParserRegistry
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


# 本 parser 负责的标号集合（八进制）。实际 bits / 编码 / port_override 等定义
# 全部来自 DeviceBundle。
_LABEL_INTS = (
    0o001, 0o002, 0o003, 0o004, 0o005, 0o006, 0o007,
    0o011, 0o012, 0o013,
    0o051,
    0o060, 0o061, 0o062, 0o063,
    0o070, 0o071, 0o072, 0o073,
    0o114, 0o115, 0o116, 0o117,
    0o170, 0o171, 0o172, 0o173, 0o174, 0o175, 0o176, 0o177,
    0o312, 0o313, 0o314,
    0o351, 0o352, 0o353,
    0o362, 0o363, 0o364,
)

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_INTS)


@ParserRegistry.register
class BrakeParser(Arinc429Mixin, BaseParser):
    parser_key = "brake_v7.3"
    name = "机轮刹车系统"
    supported_ports: List[int] = [7087, 7088, 7089, 7090, 8032, 8033, 8034]

    _LABEL_INTS = _LABEL_INTS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL

    def __init__(self):
        self._mixin_init()
        self._current_port: Optional[int] = None

    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        self._current_port = port
        return super().parse_packet(payload, port, timestamp, field_layout)

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
    # bundle-driven 解码；port_overrides（L005/006/007 下行）由
    # Arinc429Mixin._decode_with_bundle 内部处理。
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
        """Brake 复合摘要列：L353 fcc_master 的文本映射。"""
        if label == 0o353:
            v = record.get(f"{pfx}.fcc_master")
            if v is not None:
                record[f"{pfx}.fcc_master_enum"] = _FCC_MASTER_TEXT.get(
                    int(v), f"未知({v})"
                )
