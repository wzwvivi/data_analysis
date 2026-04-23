# -*- coding: utf-8 -*-
"""
无线电高度表 (RA) 解析器（bundle-only）

实现依据：
- 转换后的ICD6.0.1（260306）.xlsx（端口/偏移）
- 无线电高度表429协议-V1.0.docx（Label定义，承载在 DeviceBundle）

解析端口：
- RA1: 7007(L164/L165), 7008(L270), 7009(L350)
- RA2: 7010(L164/L165), 7011(L270), 7012(L350)

输出列名统一为 ``label_XXX.字段``；每个 Label 还附加
``.sdi / .ssm / .ssm_enum / .parity``。全部列名和字段定义由 DeviceBundle 决定。
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
    3: "正常工作",
}

_RA_SDI_TEXT = {
    0: "不使用",
    1: "左侧",
    2: "右侧",
    3: "中心",
}


# 本 parser 负责的标号集合（八进制）。实际字段定义（bits / 编码 / values）
# 全部来自 DeviceBundle；这里只是告诉 Mixin 在 ICD field_layout 匹配时应当
# 认可哪些标号，以及在 _FIELD_NAME_TO_LABEL 里生成 L164 / label_164 等别名。
_LABEL_INTS = (0o164, 0o165, 0o270, 0o350)

_FIELD_NAME_TO_LABEL = build_field_name_to_label(_LABEL_INTS)


@ParserRegistry.register
class RAParser(Arinc429Mixin, BaseParser):
    parser_key = "ra_v1.0"
    name = "无线电高度表"
    display_name = "无线电高度表"
    parser_version = "V1.0"
    protocol_family = "ra"
    supported_ports = [7007, 7008, 7009, 7010, 7011, 7012]

    _LABEL_INTS = _LABEL_INTS
    _FIELD_NAME_TO_LABEL = _FIELD_NAME_TO_LABEL

    def __init__(self):
        self._mixin_init()

    def can_parse_port(self, port: int) -> bool:
        return port in self.supported_ports

    def _common_columns(self) -> List[str]:
        return ["timestamp", "ra_id", "ra_id_cn"]

    def _ssm_text(self, ssm: int) -> str:
        return _SSM_TEXT.get(int(ssm), str(ssm))

    def _write_device_id(self, record: Dict[str, Any], sdi: int) -> None:
        record["ra_id"] = sdi
        record["ra_id_cn"] = _RA_SDI_TEXT.get(sdi, f"SDI={sdi}")

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
        """拼接 RA 各 label 的复合摘要字段（读已有原子列）。"""
        get = lambda k, default="": record.get(f"{pfx}.{k}", default)  # noqa: E731
        if label == 0o165:
            sign = record.get(f"{pfx}.ssm")
            if sign is not None:
                record[f"{pfx}.alt_bcd_sign"] = sign
                record[f"{pfx}.alt_bcd_sign_enum"] = {
                    0: "正",
                    1: "非计算数据",
                    2: "功能测试",
                    3: "负",
                }.get(int(sign), str(sign))
        elif label == 0o270:
            if word is not None and record.get(f"{pfx}.discrete") is None:
                record[f"{pfx}.discrete"] = ARINC429Decoder.extract_data_bits(word, 11, 29)
            record[f"{pfx}.discrete_enum"] = (
                f"高度数据:{get('alt_valid_enum')},"
                f"自检:{get('selftest_enum')},"
                f"AID20:{get('aid20_enum')},"
                f"AID40:{get('aid40_enum')},"
                f"AID57:{get('aid57_enum')}"
            )
        elif label == 0o350:
            if word is not None and record.get(f"{pfx}.bit_status") is None:
                record[f"{pfx}.bit_status"] = ARINC429Decoder.extract_data_bits(word, 11, 29)
            names = [
                "ra_status", "source_signal", "aid_detect", "fpga_monitor",
                "volt_5v", "volt_15v", "volt_28v", "tx_channel",
                "rx_channel_a", "rx_channel_b", "tx429_ch1", "tx429_ch2",
                "rx_antenna", "tx_antenna", "clock1", "clock2",
            ]
            faults: List[str] = []
            for n in names:
                v = record.get(f"{pfx}.{n}")
                if v == 1:
                    faults.append(f"{n}:{get(n + '_enum')}")
            record[f"{pfx}.bit_status_enum"] = (
                "正常" if not faults else "异常:" + ",".join(faults)
            )
