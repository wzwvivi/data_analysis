# -*- coding: utf-8 -*-
"""
ARINC 429 解析器公共 Mixin

将 7 个 ARINC 429 解析器（RA、ADC、Turn、Brake、LGCU、JZXPDR113B、ATG）
中重复的常量、工具函数和方法抽取到此模块。

子类只需提供：
  - _LABEL_DEFS        : Dict[int, dict]       标号定义表
  - _FIELD_NAME_TO_LABEL: Dict[str, int]        字段名→标号映射
  - _OUTPUT_COLUMNS     : List[str]             全量输出列
  - _PORT_LABELS        : Dict[int, List[int]]  (可选) 端口→标号映射
  - _decode_word(record, word, label)           具体解码逻辑
"""
import struct
from typing import Any, Dict, List, Optional

from .base import FieldLayout
from .arinc429 import ARINC429Decoder

TSN_HEADER_LEN = 8

SKIP_FIELDS = frozenset({'协议填充', '功能状态集'})


def label_prefix(label_octal: int) -> str:
    """label_164 / label_003 等统一前缀。"""
    return f"label_{oct(label_octal)[2:].zfill(3)}"


def parity_ok(word: int) -> str:
    """ARINC 429 奇校验判定。"""
    return "通过" if (bin(word).count("1") % 2 == 1) else "不通过"


def build_field_name_to_label(label_defs: Dict[int, dict]) -> Dict[str, int]:
    """
    从 _LABEL_DEFS 自动生成 FIELD_NAME_TO_LABEL 映射。
    兼容 L306 / 306 / Label306 / label_306 四种格式。
    同时为每个 Label 生成 N 后缀映射（如 L306N），
    用于匹配 ICD 中的冗余/反相字段名。
    """
    mapping: Dict[str, int] = {}
    for oct_val in label_defs:
        num_str = oct(oct_val)[2:].zfill(3)
        mapping[f"L{num_str}"] = oct_val
        mapping[num_str] = oct_val
        mapping[f"Label{num_str}"] = oct_val
        mapping[f"label_{num_str}"] = oct_val
        mapping[f"L{num_str}N"] = oct_val
        mapping[f"{num_str}N"] = oct_val
    return mapping


class Arinc429Mixin:
    """
    ARINC 429 解析器公共逻辑 Mixin。

    子类必须设置以下类属性（或模块级变量通过属性暴露）：
      _LABEL_DEFS          : Dict[int, dict]
      _FIELD_NAME_TO_LABEL : Dict[str, int]
      _OUTPUT_COLUMNS      : List[str]
      _PORT_LABELS         : Optional[Dict[int, List[int]]]  (默认 None)

    子类必须实现：
      _decode_word(self, record, word, label) -> None
    """

    _LABEL_DEFS: Dict[int, dict] = {}
    _FIELD_NAME_TO_LABEL: Dict[str, int] = {}
    _OUTPUT_COLUMNS: List[str] = []
    _PORT_LABELS: Optional[Dict[int, List[int]]] = None

    # 功能状态集中，字节值为 0x03 代表对应槽位有效（按解析思路文档约定）
    _VALID_STATUS_VALUE: int = 0x03

    def _mixin_init(self):
        """在子类 __init__ 中调用，初始化公共状态。"""
        self.decoder = ARINC429Decoder()
        self._port_columns_cache: Dict[int, List[str]] = {}

    # ------------------------------------------------------------------
    # MR4: Bundle 查询（覆盖硬编码 _PORT_LABELS）
    # ------------------------------------------------------------------
    def _get_port_labels(self, port: int) -> Optional[List[int]]:
        """返回指定端口允许的八进制 label 列表。

        优先级：bundle（版本化）> _PORT_LABELS（硬编码 fallback）> None（无过滤）

        Bundle 里 `bundle.ports[port].arinc_labels` 形如 ['L306','L003']。
        `Bundle.arinc_label_ints()` 会把它们转成 [0o306, 0o003]。
        """
        bundle = getattr(self, "_runtime_bundle", None)
        if bundle is not None:
            try:
                labels = bundle.arinc_label_ints(int(port))
            except AttributeError:
                labels = []
            if labels:
                return labels
        if self._PORT_LABELS is not None:
            return self._PORT_LABELS.get(port)
        return None

    def set_bundle(self, bundle: Any) -> None:  # type: ignore[override]
        """Bundle 注入钩子：清空端口列缓存，让 get_output_columns 重算。"""
        super().set_bundle(bundle) if hasattr(super(), "set_bundle") else None
        self._runtime_bundle = bundle
        self._port_columns_cache.clear()

    def _extract_status_slots(
        self,
        payload: bytes,
        offset: int,
        length: int,
    ) -> Optional[List[int]]:
        """从 payload 指定区间提取功能状态集字节列表。"""
        if length <= 0 or offset < 0:
            return None
        end = offset + length
        if end > len(payload):
            return None
        raw = payload[offset:end]
        if not raw:
            return None
        return list(raw)

    def _status_slot_is_valid(self, status_slots: Optional[List[int]], slot_index: int) -> bool:
        """
        判断当前槽位是否有效。
        - 无状态集时：默认有效（兼容历史行为）
        - 槽位越界时：默认有效（避免未知布局被误杀）
        - 槽位值等于 _VALID_STATUS_VALUE 时：有效
        """
        if status_slots is None:
            return True
        if slot_index < 0 or slot_index >= len(status_slots):
            return True
        return status_slots[slot_index] == self._VALID_STATUS_VALUE

    # ------------------------------------------------------------------
    # parse_packet 分发
    # ------------------------------------------------------------------
    def parse_packet(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: Optional[List[FieldLayout]] = None,
    ) -> Optional[Dict[str, Any]]:
        if field_layout:
            return self._parse_with_layout(payload, port, timestamp, field_layout)
        return self._parse_with_scan(payload, port, timestamp)

    # ------------------------------------------------------------------
    # 方法 A：基于 ICD field_layout 精确定位
    # ------------------------------------------------------------------
    def _parse_with_layout(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
        field_layout: List[FieldLayout],
    ) -> Optional[Dict[str, Any]]:
        port_cols = self.get_output_columns(port)
        record: Dict[str, Any] = {c: None for c in port_cols}
        record["timestamp"] = timestamp
        found_any = False

        status_slots: Optional[List[int]] = None
        status_idx = 0

        for field in field_layout:
            if field.field_name == '功能状态集':
                status_slots = self._extract_status_slots(payload, field.field_offset, field.field_length)
                status_idx = 0
                continue
            if field.field_name in SKIP_FIELDS:
                continue

            slot_valid = self._status_slot_is_valid(status_slots, status_idx)
            status_idx += 1
            if not slot_valid:
                continue

            label_octal = self._FIELD_NAME_TO_LABEL.get(field.field_name)
            if label_octal is None:
                continue
            if field.field_offset + field.field_length > len(payload):
                continue
            word_bytes = payload[field.field_offset: field.field_offset + field.field_length]
            if len(word_bytes) < 4:
                continue
            word = struct.unpack(">I", word_bytes[:4])[0]
            if word == 0:
                continue

            found_any = True
            self._decode_word(record, word, label_octal)

        if found_any:
            self._post_process(record)
            return record
        return None

    # ------------------------------------------------------------------
    # 方法 B（回退）：大端序盲扫
    # ------------------------------------------------------------------
    def _parse_with_scan(
        self,
        payload: bytes,
        port: int,
        timestamp: float,
    ) -> Optional[Dict[str, Any]]:
        if len(payload) < TSN_HEADER_LEN + 4:
            return None

        port_cols = self.get_output_columns(port)
        labels_for_port = self._get_port_labels(port)
        if labels_for_port is not None:
            allowed_labels = set(labels_for_port)
        else:
            allowed_labels = set(self._LABEL_DEFS.keys())

        status_slots = self._extract_status_slots(payload, 4, 4)
        status_idx = 0
        data = payload[TSN_HEADER_LEN:]
        record: Dict[str, Any] = {c: None for c in port_cols}
        record["timestamp"] = timestamp
        found_any = False

        offset = 0
        while offset + 4 <= len(data):
            word = struct.unpack(">I", data[offset: offset + 4])[0]
            offset += 4

            slot_valid = self._status_slot_is_valid(status_slots, status_idx)
            status_idx += 1
            if not slot_valid:
                continue
            if word == 0:
                continue

            label = self.decoder.extract_label(word)
            if label not in allowed_labels:
                continue
            if label not in self._LABEL_DEFS:
                continue

            found_any = True
            self._decode_word(record, word, label)

        if found_any:
            self._post_process(record)
            return record
        return None

    # ------------------------------------------------------------------
    # get_output_columns（带端口级缓存 + _PORT_LABELS 过滤）
    # 子类如需自定义列生成可覆盖 _columns_for_label
    # ------------------------------------------------------------------
    def get_output_columns(self, port: int) -> List[str]:
        if port in self._port_columns_cache:
            return list(self._port_columns_cache[port])

        labels = self._get_port_labels(port)
        if labels:
            common = self._common_columns()
            cols = common[:]
            for lb in sorted(labels):
                cols.extend(self._columns_for_label(lb))
            self._port_columns_cache[port] = cols
            return list(cols)

        self._port_columns_cache[port] = list(self._OUTPUT_COLUMNS)
        return list(self._OUTPUT_COLUMNS)

    def _common_columns(self) -> List[str]:
        """返回公共列（timestamp + 设备ID列），子类可覆盖。"""
        return ["timestamp"]

    def _columns_for_label(self, label: int) -> List[str]:
        """返回单个 Label 的列名列表，子类应覆盖。"""
        return []

    # ------------------------------------------------------------------
    # 钩子：子类可覆盖以在 record 返回前做后处理
    # ------------------------------------------------------------------
    def _post_process(self, record: Dict[str, Any]) -> None:
        """在 _parse_with_layout / _parse_with_scan 返回 record 前调用。"""
        pass

    # ------------------------------------------------------------------
    # _decode_word 占位，子类必须实现
    # ------------------------------------------------------------------
    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        raise NotImplementedError
