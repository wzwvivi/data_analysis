# -*- coding: utf-8 -*-
"""ARINC 429 通用 bundle 驱动解码器

提供 5 个纯函数（无副作用、不依赖 self、不写 record），由
``Arinc429Mixin._decode_with_bundle`` 编排调用。

输入全部来自 ``DeviceBundle.label(label_dec)`` 返回的 ``DeviceLabel`` 对象，
因此 parser 层不再需要自己维护 bit→字段名/分辨率/枚举这些表。

职责划分：
- parser 仍负责：通用帧头（sdi/ssm/ssm_enum/parity）+ 设备 ID 列
  （ra_id/adru_id 等）+ 复合摘要列（discrete_enum / fault_word_enum 等）
- 本模块负责：按 ICD 语义把 word 拆成「原子列」字典，便于 parser merge

"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .arinc429 import ARINC429Decoder


# ---------------------------------------------------------------------------
#  BNR 解码
# ---------------------------------------------------------------------------

_SIGN_STYLES = frozenset({
    "bit29_sign_magnitude",
    "twos_complement",
    "in_field_sign",
})


def _decode_one_bnr(
    word: int,
    data_bits: Tuple[int, int],
    *,
    resolution: float,
    signed: bool,
    sign_style: str,
    sign_bit: Optional[int],
) -> float:
    """根据 sign_style 分派的单 BNR 字段解码。

    data_bits = (lsb_bit, msb_bit)，1-indexed，包含两端。
    """
    lsb_bit, msb_bit = int(data_bits[0]), int(data_bits[1])
    raw = ARINC429Decoder.extract_data_bits(word, lsb_bit, msb_bit)

    if not signed:
        return raw * resolution

    style = sign_style if sign_style in _SIGN_STYLES else "bit29_sign_magnitude"

    if style == "twos_complement":
        nbits = msb_bit - lsb_bit + 1
        sign_mask = 1 << (nbits - 1)
        if raw & sign_mask:
            raw -= (1 << nbits)
        return raw * resolution

    if style == "in_field_sign":
        sb = int(sign_bit) if sign_bit is not None else msb_bit
        sign = ARINC429Decoder.extract_data_bits(word, sb, sb)
        value = raw * resolution
        return -value if sign else value

    # bit29_sign_magnitude（默认）：bit 29 = 符号位
    sign = ARINC429Decoder.extract_sign_bit(word)
    value = raw * resolution
    return -value if sign else value


def decode_bnr_from_bundle(
    word: int,
    bundle_label: Any,
    *,
    round_digits: int = 8,
    default_signed: bool = False,
) -> Dict[str, float]:
    """遍历 ``bundle_label.bnr_fields``，返回 ``{name: numeric_value}``。

    支持多段 BNR（如几何位置 label_310 高 20 位 + label_313 低 11 位的情况：
    多段可共用同一 ``name``，上层再合并）。
    """
    out: Dict[str, float] = {}
    fields = getattr(bundle_label, "bnr_fields", None) or []
    for bf in fields:
        name = str(getattr(bf, "name", "") or "").strip()
        if not name:
            continue
        data_bits = list(getattr(bf, "data_bits", []) or [])
        if len(data_bits) != 2:
            continue
        resolution = getattr(bf, "resolution", None)
        if resolution is None:
            resolution = 1.0
        signed_flag = getattr(bf, "signed", None)
        if signed_flag is None:
            # 兼容老 bundle：未声明时用调用方 default
            signed_flag = bool(default_signed)
        sign_style = str(getattr(bf, "sign_style", "") or "bit29_sign_magnitude")
        sign_bit = getattr(bf, "sign_bit", None)
        try:
            val = _decode_one_bnr(
                word,
                (int(data_bits[0]), int(data_bits[1])),
                resolution=float(resolution),
                signed=bool(signed_flag),
                sign_style=sign_style,
                sign_bit=sign_bit,
            )
        except (TypeError, ValueError):
            continue
        out[name] = round(val, round_digits)
    return out


# ---------------------------------------------------------------------------
#  Discrete 解码
# ---------------------------------------------------------------------------

def _values_lookup(values: Dict[str, str], key: int) -> str:
    """查 values 映射，fallback 返回空串。"""
    try:
        return str(values.get(str(int(key))) or "")
    except (TypeError, ValueError):
        return ""


def decode_discrete_from_bundle(
    word: int,
    bundle_label: Any,
) -> Dict[str, Any]:
    """遍历 ``discrete_bits[]`` + ``discrete_bit_groups[]``，返回每字段原始值 +
    可选 ``_enum`` 文本。

    输出形如 ``{name: raw_int, name_enum: "..."}``；当 bundle 的 ``values``
    为空时不写 ``name_enum`` 列（上游 parser 可选加补充摘要）。
    """
    out: Dict[str, Any] = {}
    eb = ARINC429Decoder.extract_data_bits

    # 单 bit
    for item in getattr(bundle_label, "discrete_bits", None) or []:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        bit = int(getattr(item, "bit", 0) or 0)
        if bit < 1 or bit > 32:
            continue
        raw = eb(word, bit, bit)
        out[name] = raw
        values_map = dict(getattr(item, "values", None) or {})
        if values_map:
            enum_text = _values_lookup(values_map, raw)
            if enum_text:
                out[f"{name}_enum"] = enum_text

    # 多 bit 枚举
    for grp in getattr(bundle_label, "discrete_bit_groups", None) or []:
        name = str(getattr(grp, "name", "") or "").strip()
        if not name:
            continue
        bits = list(getattr(grp, "bits", []) or [])
        if len(bits) != 2:
            continue
        try:
            lo, hi = int(bits[0]), int(bits[1])
        except (TypeError, ValueError):
            continue
        if lo > hi:
            lo, hi = hi, lo
        raw = eb(word, lo, hi)
        out[name] = raw
        values_map = dict(getattr(grp, "values", None) or {})
        if values_map:
            enum_text = _values_lookup(values_map, raw)
            if enum_text:
                out[f"{name}_enum"] = enum_text

    return out


# ---------------------------------------------------------------------------
#  BCD 解码
# ---------------------------------------------------------------------------

def decode_bcd_from_bundle(
    word: int,
    bundle_label: Any,
    *,
    ssm: Optional[int] = None,
) -> Dict[str, Any]:
    """按 ``bcd_pattern.digits[]`` 依序提取数位并按 ``weight`` 加权求和。

    - 每个 ``digit`` 的 ``data_bits=[lsb_bit, msb_bit]`` + ``weight`` + 可选
      ``mask``（形如 ``"0x07"``）。parser 里 ADC L233/234 的 thousands 数位
      就是 4 bit 但 mask=0x07，要求先截掉最高位。
    - ``bcd_pattern.sign_from_ssm`` 映射 SSM → 符号（``{"3": -1}``）：RA L165
      的 SSM=3 代表数值取负。

    返回 ``{col_name: value}``，col_name = bundle_label.bnr_fields / bundle_label.name
    + "bcd" 需要上游决定如何写 record。这里只返回带命名的 **单值字典**，
    key 固定为 ``"_bcd_value"``（上游 parser 自己挑 col）。
    """
    pattern = getattr(bundle_label, "bcd_pattern", None)
    if pattern is None:
        return {}
    digits = list(getattr(pattern, "digits", None) or [])
    if not digits:
        return {}

    eb = ARINC429Decoder.extract_data_bits
    total = 0.0
    any_digit_invalid = False
    for d in digits:
        bits = list(getattr(d, "data_bits", []) or [])
        if len(bits) != 2:
            continue
        lo, hi = int(bits[0]), int(bits[1])
        if lo > hi:
            lo, hi = hi, lo
        val = eb(word, lo, hi)
        mask_str = getattr(d, "mask", None)
        if mask_str:
            try:
                mask = int(str(mask_str), 0)
                val &= mask
            except (TypeError, ValueError):
                pass
        if val > 9:
            any_digit_invalid = True
        weight = getattr(d, "weight", None)
        if weight is None:
            weight = 1
        try:
            total += float(val) * float(weight)
        except (TypeError, ValueError):
            continue

    sign_map_raw = getattr(pattern, "sign_from_ssm", None) or {}
    if ssm is not None and sign_map_raw:
        try:
            mult = int(sign_map_raw.get(str(int(ssm)), 1) or 1)
        except (TypeError, ValueError):
            mult = 1
        if mult != 1:
            total *= mult

    return {
        "_bcd_value": total,
        "_bcd_invalid": any_digit_invalid,
    }


# ---------------------------------------------------------------------------
#  Port overrides
# ---------------------------------------------------------------------------

def apply_port_override(
    record: Dict[str, Any],
    bundle_label: Any,
    port: Optional[int],
    pfx: str,
) -> None:
    """按 ``bundle_label.port_overrides[port]`` 在 record 上应用端口级覆盖。

    目前支持的覆盖键（对 Brake 下行 L005/006/007 足够）：
    - ``col``：把同 label 下的默认 col 列重命名为 port_specific 的 col
    - ``resolution``：若原列是 BNR 并且覆盖了 resolution，按比例换算
    - ``unit``：单纯信息透传（parser 不消费）

    注意：parser 已经把原始列写进 record，本函数做的是 **就地重命名/换算**。
    如果找不到覆盖或 port is None，直接返回。
    """
    if port is None:
        return
    overrides = getattr(bundle_label, "port_overrides", None) or {}
    try:
        ov = dict(overrides.get(str(int(port))) or {})
    except (TypeError, ValueError):
        ov = {}
    if not ov:
        return

    new_col = ov.get("col")
    new_res = ov.get("resolution")
    # 找到 label 的"主 col"：默认从 bnr_fields[0].name 或 label.name 取
    default_col = None
    bnr_fields = getattr(bundle_label, "bnr_fields", None) or []
    if bnr_fields:
        default_col = str(getattr(bnr_fields[0], "name", "") or "") or None
    if default_col is None:
        return
    old_key = f"{pfx}.{default_col}"
    if old_key not in record:
        return
    value = record[old_key]

    # resolution 换算（假设原值是 raw_count * old_res，新值 = raw_count * new_res）
    if new_res is not None and value is not None:
        try:
            old_res = float(getattr(bnr_fields[0], "resolution", 1.0) or 1.0)
            scale = float(new_res) / old_res if old_res else 1.0
            if scale != 1.0:
                value = value * scale
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    if new_col:
        record.pop(old_key, None)
        record[f"{pfx}.{new_col}"] = value
    else:
        record[old_key] = value


# ---------------------------------------------------------------------------
#  SSM semantics
# ---------------------------------------------------------------------------

def apply_ssm_semantics(
    record: Dict[str, Any],
    bundle_label: Any,
    ssm: int,
    pfx: str,
) -> None:
    """按 ``bundle_label.ssm_semantics`` 覆盖 ``{pfx}.ssm_enum`` 的文本。

    用法：RA L165 bcd_alt 里 SSM=3 不是"正常数据"，而是"负号"；
    在 bundle 里配置 ``ssm_semantics = {"3": "负", ...}`` 后，
    parser 的默认 ssm_enum 就会被覆盖。
    """
    sem = getattr(bundle_label, "ssm_semantics", None) or {}
    if not sem:
        return
    try:
        key = str(int(ssm))
    except (TypeError, ValueError):
        return
    text = sem.get(key)
    if text:
        record[f"{pfx}.ssm_enum"] = str(text)


# ---------------------------------------------------------------------------
#  工具：枚举输出列列表（给 get_output_columns 用）
# ---------------------------------------------------------------------------

def iter_atomic_columns(bundle_label: Any) -> Iterable[str]:
    """根据 bundle_label 枚举"原子输出列名"（不含 pfx、不含 sdi/ssm/parity）。

    - 每个 BNR 字段输出一列 ``name``
    - 每个 discrete_bit / discrete_bit_group 输出 ``name``；有 values 时附加
      ``name_enum``
    - bcd_pattern：不在这里枚举（BCD 输出列名由 parser 代码通过复合摘要决定）
    """
    for bf in getattr(bundle_label, "bnr_fields", None) or []:
        nm = str(getattr(bf, "name", "") or "").strip()
        if nm:
            yield nm
    for item in getattr(bundle_label, "discrete_bits", None) or []:
        nm = str(getattr(item, "name", "") or "").strip()
        if not nm:
            continue
        yield nm
        if getattr(item, "values", None):
            yield f"{nm}_enum"
    for grp in getattr(bundle_label, "discrete_bit_groups", None) or []:
        nm = str(getattr(grp, "name", "") or "").strip()
        if not nm:
            continue
        yield nm
        if getattr(grp, "values", None):
            yield f"{nm}_enum"
