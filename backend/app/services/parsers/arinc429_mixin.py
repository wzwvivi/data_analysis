# -*- coding: utf-8 -*-
"""
ARINC 429 解析器公共 Mixin（bundle-only 版本）

将 5 个 bundle-driven ARINC 429 解析器（RA、ADC、Turn、Brake、LGCU）
中重复的常量、工具函数和方法抽取到此模块。另外两个使用扁平列名输出的
parser（JZXPDR113B、ATG CPE）不继承本 Mixin 的通用 _decode_with_bundle
分派，但仍通过 set_device_bundle 拿到同一份 DeviceBundle 做编辑器语义。

子类需要提供：
  - _LABEL_INTS        : Iterable[int]          本 parser 负责的标号（八进制 int）集合
  - _FIELD_NAME_TO_LABEL: Dict[str, int]        字段名→标号映射（build_field_name_to_label 构造）
  - _decode_word(record, word, label)           具体解码逻辑（转调 _decode_with_bundle）

**职责划分**：
- 端口路由（port → arinc_labels）和字段偏移（field_offset / length）
  由 TSN 网络协议承载；parse 阶段由 ParserService 注入 runtime_bundle。
- Label 定义（bits / 编码 / 单位 / SSM 语义 / port override 等）由
  DeviceBundle 承载，通过 ``set_device_bundle`` 注入；parser 在运行期
  只读 bundle，不再保留硬编码 label defs 兜底。如果 bundle 未注入或
  label 不在 bundle 中，该 word 会被直接跳过（不再落入空列）。
"""
import logging
import re
import struct
from typing import Any, Dict, Iterable, List, Optional

# 列名安全：不允许含 CJK / 空格 / 全角标点等，防止中文显示名被错当成输出列名。
_SAFE_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_safe_col(name: Any) -> bool:
    s = str(name or "").strip()
    if not s:
        return False
    return bool(_SAFE_COL_RE.match(s))

from .base import FieldLayout
from .arinc429 import ARINC429Decoder
from . import arinc429_generic as generic

TSN_HEADER_LEN = 8

SKIP_FIELDS = frozenset({'协议填充', '功能状态集'})

_logger = logging.getLogger(__name__)


def label_prefix(label_octal: int) -> str:
    """label_164 / label_003 等统一前缀。"""
    return f"label_{oct(label_octal)[2:].zfill(3)}"


def parity_ok(word: int) -> str:
    """ARINC 429 奇校验判定。"""
    return "通过" if (bin(word).count("1") % 2 == 1) else "不通过"


def build_field_name_to_label(label_ints: Iterable[int]) -> Dict[str, int]:
    """
    从一组八进制 label 自动生成 FIELD_NAME_TO_LABEL 映射。
    兼容 L306 / 306 / Label306 / label_306 四种格式。
    同时为每个 Label 生成 N 后缀映射（如 L306N），
    用于匹配 ICD 中的冗余/反相字段名。

    ``label_ints`` 支持 dict / tuple / list 等任何可迭代；对 dict 会取 keys。
    """
    mapping: Dict[str, int] = {}
    for oct_val in label_ints:
        num_str = oct(int(oct_val))[2:].zfill(3)
        mapping[f"L{num_str}"] = int(oct_val)
        mapping[num_str] = int(oct_val)
        mapping[f"Label{num_str}"] = int(oct_val)
        mapping[f"label_{num_str}"] = int(oct_val)
        mapping[f"L{num_str}N"] = int(oct_val)
        mapping[f"{num_str}N"] = int(oct_val)
    return mapping


class Arinc429Mixin:
    """
    ARINC 429 解析器公共逻辑 Mixin（bundle-only）。

    子类必须设置以下类属性：
      _LABEL_INTS          : Iterable[int]     本 parser 负责的标号集合（八进制 int）
      _FIELD_NAME_TO_LABEL : Dict[str, int]    由 build_field_name_to_label(_LABEL_INTS) 生成

    子类必须实现：
      _decode_word(self, record, word, label) -> None

    端口 → labels 路由由 TSN runtime_bundle 提供；label 定义由 device_bundle 提供。
    parser 不再持有硬编码 label defs。
    """

    _LABEL_INTS: Iterable[int] = ()
    _FIELD_NAME_TO_LABEL: Dict[str, int] = {}

    # 功能状态集中，字节值为 0x03 代表对应槽位有效（按解析思路文档约定）
    _VALID_STATUS_VALUE: int = 0x03

    def _mixin_init(self):
        """在子类 __init__ 中调用，初始化公共状态。"""
        self.decoder = ARINC429Decoder()
        self._port_columns_cache: Dict[int, List[str]] = {}
        # 设备协议 Bundle（来自 ParserService 注入；parser 按此消费 label 定义）
        self._device_bundle: Optional[Any] = None
        # 当前 parse_packet 的端口（供 port_overrides 使用；子类在 parse_packet
        # 顶部赋值一次即可）
        self._current_port: Optional[int] = None

    # ------------------------------------------------------------------
    # 端口 → 允许 label 列表（唯一来源：TSN 网络协议）
    # ------------------------------------------------------------------
    def _get_port_labels(self, port: int) -> List[int]:
        """返回指定端口允许的八进制 label 列表（来自 TSN runtime_bundle）。

        **职责划分**：port → labels 路由属于"网络拓扑"，由 TSN 网络协议版本化
        （``BundlePort.arinc_labels``）。解析任务必须选定 TSN 版本，该版本已由
        管理员激活前审核，运行期始终可信，因此**不再保留硬编码 fallback**。

        返回值语义：
        - 端口在 TSN bundle 中声明了 arinc_labels → 返回 ``[label_dec, ...]``
        - 端口未声明或 arinc_labels 为空 → 返回 ``[]``（表示该端口不接受任何
          ARINC 429 word；``_parse_with_scan`` 会整包跳过）
        - runtime_bundle 尚未注入（极罕见的错误路径）→ 返回 ``[]``
        """
        bundle = getattr(self, "_runtime_bundle", None)
        if bundle is None:
            return []
        try:
            return list(bundle.arinc_label_ints(int(port)))
        except AttributeError:
            return []

    def set_bundle(self, bundle: Any) -> None:  # type: ignore[override]
        """Bundle 注入钩子：清空端口列缓存，让 get_output_columns 重算。"""
        super().set_bundle(bundle) if hasattr(super(), "set_bundle") else None
        self._runtime_bundle = bundle
        self._port_columns_cache.clear()

    # ------------------------------------------------------------------
    # 设备协议 Bundle 注入（由 ParserService 按 parser_family 注入）
    # ------------------------------------------------------------------
    def set_device_bundle(self, device_bundle: Any) -> None:
        """注入 DeviceBundle（仅承载 label 定义；port_routing 归属 TSN bundle）。

        parser 通过 ``_get_bundle_label(label)`` 读取 bundle 里的 label 定义，
        再由 ``_decode_with_bundle`` 转派到通用解码器。
        """
        self._device_bundle = device_bundle
        self._port_columns_cache.clear()

    # ------------------------------------------------------------------
    # Label 定义查询：bundle 为唯一入口
    # ------------------------------------------------------------------
    def _get_bundle_label(self, label_int: int) -> Optional[Any]:
        """返回 DeviceBundle 里的 DeviceLabel（未注入或 miss 时返回 None）。"""
        dev_b = getattr(self, "_device_bundle", None)
        if dev_b is None:
            return None
        try:
            return dev_b.label(int(label_int))
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 通用 bundle-driven 解码入口（Phase 1/2 plan 核心）
    # ------------------------------------------------------------------
    def _decode_with_bundle(
        self,
        record: Dict[str, Any],
        word: int,
        port: Optional[int],
        bundle_label: Any,
        pfx: str,
    ) -> None:
        """根据 bundle_label.ssm_type 分派到 Phase 1 的 4 个通用函数，把结果
        合并到 record。

        - ssm_type == 'bnr'      → decode_bnr_from_bundle
        - ssm_type == 'discrete' → decode_discrete_from_bundle
        - ssm_type == 'bcd'      → decode_bcd_from_bundle（上游 parser 自行
          把 _bcd_value 映射到业务列名）
        - 其它（special 等）     → 仍由 parser 代码处理
        之后统一应用 port_overrides + ssm_semantics。
        """
        if bundle_label is None:
            return

        ssm_type = str(getattr(bundle_label, "ssm_type", "") or "").lower()
        ssm = self.decoder.extract_ssm(word)

        # BNR：每条 BNR 字段一列
        if ssm_type == "bnr" or getattr(bundle_label, "bnr_fields", None):
            bnr_values = generic.decode_bnr_from_bundle(word, bundle_label)
            for name, val in bnr_values.items():
                record[f"{pfx}.{name}"] = val

        # Discrete：bit 和 bit_groups
        if ssm_type == "discrete" or getattr(bundle_label, "discrete_bits", None) \
                or getattr(bundle_label, "discrete_bit_groups", None):
            disc = generic.decode_discrete_from_bundle(word, bundle_label)
            for name, val in disc.items():
                record[f"{pfx}.{name}"] = val

        # BCD：parser 层消费 _bcd_value（因为 col 语义与设备耦合）
        if ssm_type == "bcd" or getattr(bundle_label, "bcd_pattern", None):
            bcd = generic.decode_bcd_from_bundle(word, bundle_label, ssm=ssm)
            if bcd:
                # 主 col：label.name > bnr_fields[0].name > data_type
                main_col = self._bcd_main_col(bundle_label)
                if main_col:
                    # 即使某数位 > 9（_bcd_invalid=True）仍写入计算结果，
                    # 与 legacy _decode_bcd_alt 等行为一致（不做"无效归 None"过滤）
                    record[f"{pfx}.{main_col}"] = bcd.get("_bcd_value")

        # 端口级覆盖（Brake L005/006/007 下行改列名与分辨率）
        generic.apply_port_override(record, bundle_label, port, pfx)

        # SSM 语义覆盖（RA L165 SSM=3 → 负号文案）
        generic.apply_ssm_semantics(record, bundle_label, ssm, pfx)

    @staticmethod
    def _bcd_main_col(bundle_label: Any) -> Optional[str]:
        """挑选 BCD 结果写入的主 col。

        优先级：label.name（业务列名，与 parser legacy _LABEL_DEFS[*].col 对齐）
        → bnr_fields[0].name → data_type（最后兜底）。

        **要求**：候选必须是合法标识符（英文列名）。旧数据里 name 可能被 docx
        解析器塞进了中文显示名（如"装订气压QNH回报"），这里会自动跳过 CJK/
        非法字符名、继续向后兜底；实在没有再强制转成 snake_case。
        """
        candidates = [
            getattr(bundle_label, "name", None),
        ]
        bnr_fields = getattr(bundle_label, "bnr_fields", None) or []
        if bnr_fields:
            candidates.append(getattr(bnr_fields[0], "name", None))
        candidates.append(getattr(bundle_label, "data_type", None))
        for c in candidates:
            if _is_safe_col(c):
                return str(c).strip()
        # 最后兜底：把 data_type 小写化（如 BCD_PRESSURE → bcd_pressure）
        data_type = str(getattr(bundle_label, "data_type", "") or "").strip()
        if data_type:
            return data_type.lower()
        return None

    # ------------------------------------------------------------------
    # functional status slots（与之前保持一致）
    # ------------------------------------------------------------------
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
        # 暴露当前端口给 _decode_word（port_overrides 需要）
        self._current_port = port
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
        # TSN bundle 声明了该端口可接收的 label 列表；为空则整包跳过
        allowed_labels = set(self._get_port_labels(port))
        if not allowed_labels:
            return None

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
            # bundle 是 label 定义的唯一来源；不在 bundle 中的 label 直接丢弃。
            if self._get_bundle_label(label) is None:
                continue

            found_any = True
            self._decode_word(record, word, label)

        if found_any:
            self._post_process(record)
            return record
        return None

    # ------------------------------------------------------------------
    # get_output_columns（带端口级缓存；完全由 device_bundle 反推）
    # ------------------------------------------------------------------
    def get_output_columns(self, port: int) -> List[str]:
        if port in self._port_columns_cache:
            return list(self._port_columns_cache[port])

        common = self._common_columns()
        cols = list(common)
        labels = self._get_port_labels(port)
        for lb in sorted(labels):
            cols.extend(self._columns_for_label(lb))
        # 即使端口没有声明任何 label，也至少返回 common 列（timestamp + 设备ID），
        # 保证下游 DataFrame 有一致 schema。
        self._port_columns_cache[port] = cols
        return list(cols)

    def _common_columns(self) -> List[str]:
        """返回公共列（timestamp + 设备ID列），子类可覆盖。"""
        return ["timestamp"]

    def _columns_for_label(self, label: int) -> List[str]:
        """返回单个 Label 的列名列表，完全按 device_bundle 推导。

        bundle 缺该 label → 返回空（运行期 ``_get_bundle_label`` 拒绝后也不会
        写入任何 ``{pfx}.*`` 列，行为一致）。
        """
        bundle_label = self._get_bundle_label(label)
        if bundle_label is None:
            return []
        pfx = label_prefix(label)
        cols: List[str] = []
        for name in generic.iter_atomic_columns(bundle_label):
            cols.append(f"{pfx}.{name}")
        # 统一追加 sdi/ssm/ssm_enum/parity
        cols.extend([f"{pfx}.sdi", f"{pfx}.ssm", f"{pfx}.ssm_enum", f"{pfx}.parity"])
        return cols

    # ------------------------------------------------------------------
    # 钩子：子类可覆盖以在 record 返回前做后处理
    # ------------------------------------------------------------------
    def _post_process(self, record: Dict[str, Any]) -> None:
        """在 _parse_with_layout / _parse_with_scan 返回 record 前调用。"""
        pass

    # ------------------------------------------------------------------
    # _write_device_id / _compose_summary：子类按需覆盖
    # ------------------------------------------------------------------
    def _write_device_id(self, record: Dict[str, Any], sdi: int) -> None:
        """按 SDI 写设备级 ID 列（如 ra_id/ra_id_cn / adru_id/adru_id_cn）。

        默认实现：no-op。各 parser 子类按需覆盖。
        """
        return None

    def _compose_summary(
        self,
        record: Dict[str, Any],
        label: int,
        pfx: str,
        word: Optional[int] = None,
    ) -> None:
        """按 label 拼复合摘要字段（discrete_enum / fault_word_enum 等）。

        优先读 record 已有原子列；极少数情况下（如 ADC L137 把 bit 11/12/13
        合并成"起飞:XX,巡航:XX,着陆:XX"而 bundle 未提供每 bit 的 values）允许
        按 ``word`` 重新 extract_data_bits。默认实现 no-op。
        """
        return None

    # ------------------------------------------------------------------
    # _decode_word 占位，子类必须实现（标准骨架）：
    #
    #   def _decode_word(self, record, word, label):
    #       bundle_label = self._get_bundle_label(label)
    #       if bundle_label is None:
    #           return  # bundle 未定义此 label → 直接跳过
    #       pfx = label_prefix(label)
    #       sdi = self.decoder.extract_sdi(word)
    #       ssm = self.decoder.extract_ssm(word)
    #       self._write_device_id(record, sdi)
    #       record[f"{pfx}.sdi"] = sdi
    #       record[f"{pfx}.ssm"] = ssm
    #       record[f"{pfx}.ssm_enum"] = self._ssm_text(ssm)
    #       record[f"{pfx}.parity"] = parity_ok(word)
    #       self._decode_with_bundle(record, word, self._current_port, bundle_label, pfx)
    #       self._compose_summary(record, label, pfx, word=word)
    # ------------------------------------------------------------------
    def _ssm_text(self, ssm: int) -> str:
        """默认 SSM 文案；parser 可覆盖。"""
        return {
            0: "故障告警",
            1: "无计算数据",
            2: "功能测试",
            3: "正常工作",
        }.get(int(ssm), str(ssm))

    def _decode_word(self, record: Dict[str, Any], word: int, label: int) -> None:
        raise NotImplementedError
