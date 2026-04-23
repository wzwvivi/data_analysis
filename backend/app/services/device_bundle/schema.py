# -*- coding: utf-8 -*-
"""设备协议 Bundle 数据模型（pydantic v1/v2 兼容）

把一个 DeviceProtocolVersion.spec_json 投影成运行期友好的 JSON 结构：

- 所有 label 按 label_dec 建索引（int key），方便 parser O(1) 查
- port_overrides 的 key 统一成 int（port_number）
- sign_style / bcd_pattern / discrete_bits / discrete_bit_groups 等新字段一并携带

**职责划分**：UDP 端口 → labels 的"网络拓扑"信息由 TSN 网络配置版本化
（``services/bundle/schema.py::BundlePort.arinc_labels``），**不**属于设备 ICD。
本模块不承载 port_routing（旧 bundle.json 里可能残留的 port_routing 键在
反序列化时会被静默丢弃）。

与 `services/bundle/schema.py` 保持同构：BaseModel + `to_dict` / `from_dict`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field  # type: ignore
except Exception:  # pragma: no cover
    from pydantic.v1 import BaseModel, Field  # type: ignore


DEVICE_BUNDLE_SCHEMA_VERSION = 1


# ── 低层字段 ─────────────────────────────────────────────────────────────

class DeviceBnrField(BaseModel):
    """BNR 字段。"""
    name: str
    data_bits: List[int] = Field(default_factory=list)  # [lsb_bit, msb_bit]
    encoding: str = "bnr"                # "bnr" | "bcd" | "twos_complement"
    sign_style: str = "bit29_sign_magnitude"
    sign_bit: Optional[int] = None
    resolution: Optional[float] = None
    unit: Optional[str] = None
    signed: Optional[bool] = None


class DeviceBcdDigit(BaseModel):
    name: str
    data_bits: List[int] = Field(default_factory=list)
    weight: Optional[float] = None
    mask: Optional[str] = None  # 形如 "0x07"


class DeviceBcdPattern(BaseModel):
    digits: List[DeviceBcdDigit] = Field(default_factory=list)
    sign_from_ssm: Dict[str, int] = Field(default_factory=dict)
    description: Optional[str] = None


class DeviceDiscreteBit(BaseModel):
    """单 bit 离散位。

    `bit` = bit 位号（11..29）。为了让 JSON 既能保留结构化语义又能被旧代码
    读出字符串描述，序列化时也保留 `raw_desc`（字符串形式的 fallback）。
    """
    bit: int
    name: str = ""
    cn: str = ""
    values: Dict[str, str] = Field(default_factory=dict)
    raw_desc: Optional[str] = None  # 老数据里 value 是字符串时保留


class DeviceDiscreteBitGroup(BaseModel):
    """连续多 bit 的枚举（如 work_state bits=[14,16]）。"""
    name: str
    cn: str = ""
    bits: List[int] = Field(default_factory=list)  # [lsb_bit, msb_bit]
    values: Dict[str, str] = Field(default_factory=dict)


class DeviceSpecialField(BaseModel):
    """多段 binary / 整 word 原始值等特殊字段。"""
    name: str
    data_bits: Optional[List[int]] = None  # None 表示整 word（hex/raw/word encoding）
    encoding: str = "binary"
    values: Dict[str, str] = Field(default_factory=dict)
    description: Optional[str] = None
    unit: Optional[str] = None


# ── Label 级 ─────────────────────────────────────────────────────────────

class DeviceLabel(BaseModel):
    """一条 ARINC 429 Label 的运行期定义。"""
    label_oct: str                     # "164"
    label_dec: int                     # 0o164 = 116
    name: str = ""                     # 英文输出列名 / 主 col（parser 从这里挑 BCD 主列名）
    cn: str = ""                       # 中文显示名（docx 信号名称那一行）
    direction: str = ""
    sources: List[str] = Field(default_factory=list)
    sdi: Optional[int] = None
    ssm_type: str = "bnr"
    data_type: Optional[str] = None
    unit: Optional[str] = None
    range_desc: Optional[str] = None
    resolution: Optional[float] = None
    reserved_bits: Optional[str] = None
    notes: Optional[str] = None

    bnr_fields: List[DeviceBnrField] = Field(default_factory=list)
    bcd_pattern: Optional[DeviceBcdPattern] = None
    discrete_bits: List[DeviceDiscreteBit] = Field(default_factory=list)
    discrete_bit_groups: List[DeviceDiscreteBitGroup] = Field(default_factory=list)
    special_fields: List[DeviceSpecialField] = Field(default_factory=list)

    # 端口级覆盖：{port_str: {col, resolution, unit, encoding, ...}}
    port_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # SSM 值 → 业务语义（BCD 高度协议里 SSM=3 代表负号等）
    ssm_semantics: Dict[str, str] = Field(default_factory=dict)


# ── Bundle 顶层 ──────────────────────────────────────────────────────────

class DeviceBundle(BaseModel):
    """一个 DeviceProtocolVersion 的可序列化运行期快照。"""
    schema_version: int = DEVICE_BUNDLE_SCHEMA_VERSION

    # 来源
    device_version_id: int
    device_version_name: str = ""
    device_spec_id: int = 0
    device_id: str = ""
    device_name: str = ""
    protocol_family: str = "arinc429"
    parser_family: Optional[str] = None   # "adc" / "brake" / "ra" / ... (由 parser_family_hints 推断)
    ata_code: Optional[str] = None
    generated_at: datetime

    # label_dec → DeviceLabel（JSON 里 key 会被序列化成字符串）
    labels: Dict[int, DeviceLabel] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    # ── 便捷查找 ──

    def label(self, label_dec: int) -> Optional[DeviceLabel]:
        """按 label 的十进制值查。parser 常用写法：`bundle.label(0o164)`。"""
        return self.labels.get(int(label_dec))

    def label_by_oct(self, label_oct: str) -> Optional[DeviceLabel]:
        """按 3 位八进制字符串查（如 "164"）。"""
        try:
            return self.label(int(label_oct, 8))
        except (TypeError, ValueError):
            return None

    def override_for(
        self, label_dec: int, port: int
    ) -> Dict[str, Any]:
        """返回该 label 在该 port 下的 overrides（找不到返回 {}）。"""
        lbl = self.label(label_dec)
        if not lbl:
            return {}
        return dict(lbl.port_overrides.get(str(int(port))) or {})


# ── Pydantic v1/v2 serialization helpers ─────────────────────────────────


def _to_payload(obj: BaseModel) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")  # pydantic v2
    data = obj.dict()  # pydantic v1
    if isinstance(data.get("generated_at"), datetime):
        data["generated_at"] = data["generated_at"].isoformat() + "Z"
    return data


def device_bundle_to_dict(b: DeviceBundle) -> Dict[str, Any]:
    """DeviceBundle → JSON 兼容 dict（int key → str）。"""
    data = _to_payload(b)
    # labels: Dict[int, ...] key → str
    if isinstance(data.get("labels"), dict):
        data["labels"] = {str(k): v for k, v in data["labels"].items()}
    return data


def device_bundle_from_dict(data: Dict[str, Any]) -> DeviceBundle:
    """JSON dict → DeviceBundle，恢复 int key。

    旧 bundle.json 里残留的 ``port_routing`` 键会被显式丢弃（现已迁移到 TSN
    ``BundlePort.arinc_labels``），其他未识别字段由 pydantic 按默认策略处理。
    """
    normalized = dict(data)
    # labels: str → int
    labs = normalized.get("labels")
    if isinstance(labs, dict):
        fixed_labs: Dict[int, Any] = {}
        for k, v in labs.items():
            try:
                fixed_labs[int(k)] = v
            except (TypeError, ValueError):
                continue
        normalized["labels"] = fixed_labs
    # 显式丢弃旧 bundle 的 port_routing 键（兼容反序列化）
    normalized.pop("port_routing", None)

    if hasattr(DeviceBundle, "model_validate"):
        return DeviceBundle.model_validate(normalized)  # pydantic v2
    return DeviceBundle.parse_obj(normalized)  # pydantic v1
