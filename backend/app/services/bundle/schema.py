# -*- coding: utf-8 -*-
"""Bundle 数据模型（pydantic v1/v2 兼容）

本模块定义版本化 Bundle 的 JSON 结构。生成器（generator.py）从 DB 读出
PortDefinition/FieldDefinition 后构造这些 pydantic 模型，再序列化为
`generated/v{N}/bundle.json`。运行时由 loader.py 反序列化回来供解析器、
异常检查、事件分析三大模块消费。

设计取向：
- 字段语义宁可冗余也要自描述，避免运行时解码歧义
- `schema_version` 独立维护，后续改动走"新版本号 + 兼容 loader"
- Pydantic 兼容 v1 / v2（运行期按存在的 API 走）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    # pydantic v1
    from pydantic import BaseModel, Field  # type: ignore
except Exception:  # pragma: no cover
    from pydantic.v1 import BaseModel, Field  # type: ignore


BUNDLE_SCHEMA_VERSION = 1


class BundleField(BaseModel):
    """单个字段的 TSN 层元数据。"""
    name: str
    offset: int
    length: int
    data_type: str = "bytes"
    byte_order: str = "big"
    scale_factor: float = 1.0
    unit: Optional[str] = None
    description: Optional[str] = None


class BundleCanFrame(BaseModel):
    """CAN 协议族的端口→帧映射（来自 sidecar JSON，如 bms800v_data.json）。"""
    can_id_hex: str
    offset: int
    name: Optional[str] = None


class BundlePort(BaseModel):
    """端口级运行时元数据。

    - `arinc_labels` 由生成器从 `fields` 里按 L\\d+ 前缀衍生
    - `can_frames` 只对 CAN family 非空
    """
    port_number: int
    protocol_family: Optional[str] = None
    port_role: Optional[str] = None
    source_device: Optional[str] = None
    target_device: Optional[str] = None
    message_name: Optional[str] = None
    direction: Optional[str] = None
    period_ms: Optional[float] = None
    fields: List[BundleField] = Field(default_factory=list)
    arinc_labels: List[str] = Field(default_factory=list)
    can_frames: List[BundleCanFrame] = Field(default_factory=list)


class BundleRuleFilter(BaseModel):
    """规则里对 payload/response 的字节匹配条件。

    兼容两种引用方式：
    - `field="status_byte"` 与 bundle.ports[port].fields 名字匹配解析出 offset（推荐）
    - `offset=33` 直接写死 offset（老规则兼容）

    至少必须提供 field 或 offset 其一，并搭配 value。
    """
    field: Optional[str] = None
    offset: Optional[int] = None
    value: int


class BundleContentCheck(BaseModel):
    """规则里的 content_check 项。

    同样支持 field/offset 两种引用。decode 为 'ascii' 时需要 length + expected；
    否则用 expected_hex 做单字节比较。
    """
    field: Optional[str] = None
    offset: Optional[int] = None
    length: Optional[int] = None
    decode: Optional[str] = None  # "ascii" 或 None
    expected: Optional[str] = None
    expected_hex: Optional[str] = None


class BundleEventRule(BaseModel):
    """一条事件分析规则的 JSON 投影。

    结构与 `event_rules.checksheet.CheckItem` 对齐；offset/field 两种引用方式
    在运行时由 Checksheet._resolve_offset 解析成真实 offset。
    """
    sequence: int
    name: str
    category: str
    description: str
    port: int
    wireshark_filter: str = ""
    extra_ports: List[int] = Field(default_factory=list)
    payload_filter: List[BundleRuleFilter] = Field(default_factory=list)
    state_prerequisite_filter: List[BundleRuleFilter] = Field(default_factory=list)
    detect_mode: str = "first_match"
    expected_period_ms: Optional[int] = None
    period_tolerance_pct: float = 0.30
    content_checks: List[BundleContentCheck] = Field(default_factory=list)
    response_port: Optional[int] = None
    response_filter: List[BundleRuleFilter] = Field(default_factory=list)
    response_timeout_ms: int = 1000
    response_description: str = ""
    response_burst_count: int = 0
    response_burst_threshold_ms: float = 10.0
    response_ports: List[int] = Field(default_factory=list)
    response_window_count: int = 0
    response_window_ms: float = 200.0


# Back-compat alias (plan uses BundleRule)
BundleRule = BundleEventRule


class BundleCompareProfile(BaseModel):
    """TSN 异常检查（compare_service）的算法阈值。"""
    sync_pass_ms: float = 1.0
    sync_warning_ms: float = 100.0
    gap_threshold_factor: float = 3.0
    jitter_compliance_pass_pct: float = 95.0
    jitter_compliance_warning_pct: float = 80.0
    default_jitter_threshold_pct: float = 10.0


class Bundle(BaseModel):
    """按 ProtocolVersion 版本号落盘的数据包。"""
    schema_version: int = BUNDLE_SCHEMA_VERSION
    protocol_version_id: int
    protocol_version_name: str = ""
    protocol_name: str = ""
    generated_at: datetime
    # key 以字符串形式序列化（JSON 标准），运行时 loader 会保持一致
    ports: Dict[int, BundlePort] = Field(default_factory=dict)
    family_ports: Dict[str, List[int]] = Field(default_factory=dict)
    port_to_family: Dict[int, str] = Field(default_factory=dict)
    # Phase 2：port_role 视图，便于 FMS/FCC/AutoFlight 模块按角色查询端口集合
    role_ports: Dict[str, List[int]] = Field(default_factory=dict)
    port_to_role: Dict[int, str] = Field(default_factory=dict)
    event_rules: Dict[str, List[BundleEventRule]] = Field(default_factory=dict)
    compare_profile: BundleCompareProfile = Field(default_factory=BundleCompareProfile)

    class Config:
        arbitrary_types_allowed = True

    # ── 便捷查找 ──
    def fields_by_name(self, port: int) -> Dict[str, BundleField]:
        """返回 {field_name: BundleField} 便于 O(1) 查找。"""
        bp = self.ports.get(port)
        if not bp:
            return {}
        return {f.name: f for f in bp.fields}

    def resolve_offset(self, port: int, field_name: str) -> Optional[int]:
        """通过字段名解析 offset，缺失返回 None。"""
        fmap = self.fields_by_name(port)
        f = fmap.get(field_name)
        return f.offset if f else None

    def can_frames_for(self, port: int) -> List[tuple]:
        """返回指定端口的 CAN 帧映射 [(can_id_int, offset), ...]。

        CAN 解析器运行时用法：替代 `_PORT_MAP.get(port)`，从 bundle 拿版本化数据。
        bundle 里 `BundleCanFrame.can_id_hex` 形如 '0x18FF1234' 或 '18FF1234'，
        这里统一解析为 int。port 不存在或 can_frames 为空返回 []。
        """
        bp = self.ports.get(port)
        if not bp or not bp.can_frames:
            return []
        out: List[tuple] = []
        for fr in bp.can_frames:
            raw = (fr.can_id_hex or "").strip()
            if not raw:
                continue
            try:
                cid = int(raw, 16)
            except ValueError:
                continue
            out.append((cid, int(fr.offset)))
        return out

    def ports_for_role(self, role: str) -> List[int]:
        """按 port_role 查询端口号列表。返回排序后的 int 列表，找不到返回 []。"""
        lst = self.role_ports.get(role) or []
        try:
            return sorted(int(p) for p in lst)
        except (TypeError, ValueError):
            return list(lst)

    def arinc_label_ints(self, port: int) -> List[int]:
        """把 port 上形如 'L306' 的字段名解析成八进制 int 列表。"""
        out: List[int] = []
        bp = self.ports.get(port)
        if not bp:
            return out
        for label in bp.arinc_labels:
            if not label:
                continue
            s = label.strip()
            if s.upper().startswith("L"):
                s = s[1:]
            try:
                out.append(int(s, 8))
            except ValueError:
                continue
        return out


# Pydantic v1/v2 serialization helpers ----------------------------------------


def bundle_to_dict(b: Bundle) -> Dict[str, Any]:
    """把 Bundle 序列化成 JSON 兼容字典（datetime → isoformat，int key → str）。"""
    if hasattr(b, "model_dump"):
        data = b.model_dump(mode="json")  # pydantic v2
    else:
        data = b.dict()  # pydantic v1
        # v1 需要手动把 datetime / int-key 处理掉
        if isinstance(data.get("generated_at"), datetime):
            data["generated_at"] = data["generated_at"].isoformat() + "Z"
    # 把 dict[int, ...] 的 key 转成 str，以便 json.dumps 能 roundtrip
    for key in ("ports", "port_to_family", "port_to_role"):
        if key in data and isinstance(data[key], dict):
            data[key] = {str(k): v for k, v in data[key].items()}
    return data


def bundle_from_dict(data: Dict[str, Any]) -> Bundle:
    """反序列化：把 JSON dict 还原成 Bundle。兼容 int-key 的字符串表示。"""
    normalized = dict(data)
    for key in ("ports", "port_to_family", "port_to_role"):
        v = normalized.get(key)
        if isinstance(v, dict):
            fixed: Dict[int, Any] = {}
            for k, val in v.items():
                try:
                    fixed[int(k)] = val
                except (TypeError, ValueError):
                    continue
            normalized[key] = fixed
    if hasattr(Bundle, "model_validate"):
        return Bundle.model_validate(normalized)  # pydantic v2
    return Bundle.parse_obj(normalized)  # pydantic v1
