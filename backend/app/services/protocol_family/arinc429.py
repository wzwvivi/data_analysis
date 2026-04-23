# -*- coding: utf-8 -*-
"""ARINC429 协议族 Handler

spec_json 结构（移植自桌面 generator + parser 硬编码规律提炼）：
{
    "protocol_meta": {
        "name": "设备名",
        "version": "V2.0",
        "description": "...",
        "generated_at": "...",
    },

    # 注：port_routing（UDP 端口 → labels）归属 TSN 网络配置
    # （BundlePort.arinc_labels），不再出现在设备 ICD spec_json 中。
    # 旧版 spec_json 里残留的 port_routing 字段会被 normalize_spec 静默丢弃。

    "labels": [
        {
            "label_oct": "001",
            "label_dec": 1,
            "name": "...",
            "direction": "input" | "output",
            "sources": ["FCC", ...],
            "sdi": None | 0..3,
            "ssm_type": "bnr" | "discrete" | "bcd" | "special" | "unimplemented",
            "data_type": "...",
            "unit": "...",
            "range_desc": "...",
            "resolution": 0.1,
            "reserved_bits": "...",
            "notes": "...",

            "discrete_bits": {
                "11": "park_brk_fail",        # 旧：value 直接是字符串
                "12": {                        # 新：结构化
                    "name": "park_brk_on",
                    "cn": "停留刹车接通",
                    "values": {"0": "断开", "1": "接通"},
                },
            },
            "discrete_bit_groups": [
                {
                    "name": "flap_status",
                    "cn": "襟翼状态",
                    "bits": [11, 13],
                    "values": {"0": "收起", "1": "...", "...": "..."},
                }
            ],
            "special_fields": [
                {
                    "name",
                    "data_bits": [a, b],  # 与 bnr_fields 对齐（旧 key "bits" 也兼容）
                    "encoding": "enum"|"uint"|"bcd"|"binary"|"hex"|"raw",
                    "values": {...},
                    "description": "...",
                },
                # encoding ∈ {hex,raw,word} 时允许 data_bits 缺省（整 word 原始值）
            ],
            "bnr_fields": [
                {
                    "name",
                    "data_bits": [a, b],
                    "encoding": "bnr" | "bcd",
                    "sign_bit": int | None,
                    "sign_style":
                        "bit29_sign_magnitude"   # 默认，标准 ARINC-429
                        | "twos_complement"       # 段内补码（如 XPDR L365/366/367）
                        | "in_field_sign",        # signed 位在 data_bits 内部最高位
                    "resolution": ...,
                    "unit": ...,
                },
            ],

            # ──────────────────────────────────────────────
            # bcd_pattern（P1）：承载 bcd_alt / bcd_pressure / bcd_version
            # 这类 parser 里硬编码的非均匀数位切分
            # digits 从低位到高位，weight 按 10 的幂；mask 支持顶位掩码
            # sign_from_ssm 表达 SSM→符号（例如 RA bcd_alt: SSM=3 → -1）
            # ──────────────────────────────────────────────
            "bcd_pattern": {
                "digits": [
                    {"name": "tenths",    "data_bits": [11, 14], "weight": 0.1},
                    {"name": "ones",      "data_bits": [15, 18], "weight": 1},
                    {"name": "tens",      "data_bits": [19, 22], "weight": 10},
                    {"name": "hundreds",  "data_bits": [23, 26], "weight": 100},
                    {"name": "thousands", "data_bits": [27, 29], "weight": 1000, "mask": "0x07"},
                ],
                "sign_from_ssm": {"3": -1},
            },

            # ──────────────────────────────────────────────
            # port_overrides（P1）：端口级语义复用（如 brake L005/006/007 上下行）
            # 键为端口号字符串，值覆盖 label 级默认定义的部分字段
            # ──────────────────────────────────────────────
            "port_overrides": {
                "8032": {
                    "col": "brake_cmd_pct",
                    "resolution": 1.0,
                    "unit": "%",
                    "encoding": "bnr",
                }
            },

            # ──────────────────────────────────────────────
            # ssm_semantics（P2）：SSM 值 → 业务语义
            # 默认 {"0":"正常","1":"无计算数据","2":"功能测试","3":"故障告警"}
            # 但 BCD 协议里 SSM=3 通常代表"负号"
            # ──────────────────────────────────────────────
            "ssm_semantics": {
                "0": "正",
                "1": "无计算数据",
                "2": "功能测试",
                "3": "负",
            },
        },
        ...
    ]
}
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from .base import FamilyHandler, SpecDiff, SpecValidation


# ──────────────── 常量 ────────────────
_SSM_TYPES = frozenset({"bnr", "discrete", "bcd", "special", "unimplemented"})
_SIGN_STYLES = frozenset(
    {"bit29_sign_magnitude", "twos_complement", "in_field_sign"}
)
_DEFAULT_SIGN_STYLE = "bit29_sign_magnitude"


def _normalize_discrete_bit_value(value: Any) -> Any:
    """把 discrete_bits 里的 value 规范化。

    - str         → 原样返回（旧兼容）
    - dict        → 补齐 name/cn/values 三键，values 的 k/v 都强制成 str
    - 其它/None   → 返回 ""（空描述）
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw_values = value.get("values") or {}
        values: Dict[str, str] = {}
        if isinstance(raw_values, dict):
            for k, v in raw_values.items():
                values[str(k)] = "" if v is None else str(v)
        return {
            "name": str(value.get("name") or "").strip(),
            "cn": str(value.get("cn") or "").strip(),
            "values": values,
        }
    return str(value)


def _normalize_bit_group(item: Any) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    bits = item.get("bits")
    if isinstance(bits, (list, tuple)) and len(bits) == 2:
        try:
            bits_norm = [int(bits[0]), int(bits[1])]
        except (TypeError, ValueError):
            bits_norm = list(bits)
    else:
        bits_norm = list(bits) if isinstance(bits, (list, tuple)) else []
    raw_values = item.get("values") or {}
    values: Dict[str, str] = {}
    if isinstance(raw_values, dict):
        for k, v in raw_values.items():
            values[str(k)] = "" if v is None else str(v)
    return {
        "name": str(item.get("name") or "").strip(),
        "cn": str(item.get("cn") or "").strip(),
        "bits": bits_norm,
        "values": values,
    }


def _normalize_bnr_field(item: Any) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out = dict(item)
    sign_style = item.get("sign_style")
    if sign_style is None or sign_style == "":
        out["sign_style"] = _DEFAULT_SIGN_STYLE
    else:
        out["sign_style"] = str(sign_style)
    return out


def _normalize_special_field(item: Any) -> Dict[str, Any] | None:
    """统一 special_fields 的 key 命名。

    历史上 importer 写入 `data_bits`、schema 文档里写 `bits`——这里统一成
    `data_bits`（与 bnr_fields 对齐），老数据里的 `bits` 自动平移。
    """
    if not isinstance(item, dict):
        return None
    out = dict(item)
    if "data_bits" not in out and "bits" in out:
        out["data_bits"] = out.pop("bits")
    # 透传 type / encoding 两种写法
    if "type" in out and "encoding" not in out:
        out["encoding"] = out["type"]
    return out


# encoding 值落在这些里时，special_field 允许不带 data_bits（表示"整 word"）
_WHOLE_WORD_SPECIAL_ENCODINGS = frozenset({"hex", "raw", "word"})


# ──────────────── P1/P2 normalizers ────────────────

def _normalize_bcd_digit(item: Any) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    bits = item.get("data_bits") if "data_bits" in item else item.get("bits")
    if isinstance(bits, (list, tuple)) and len(bits) == 2:
        try:
            bits_norm = [int(bits[0]), int(bits[1])]
        except (TypeError, ValueError):
            bits_norm = list(bits)
    else:
        bits_norm = []
    out: Dict[str, Any] = {
        "name": str(item.get("name") or "").strip(),
        "data_bits": bits_norm,
    }
    if "weight" in item and item["weight"] is not None:
        out["weight"] = item["weight"]
    if "mask" in item and item["mask"] not in (None, ""):
        out["mask"] = str(item["mask"])
    return out


def _normalize_bcd_pattern(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    digits: List[Dict[str, Any]] = []
    for d in value.get("digits") or []:
        norm = _normalize_bcd_digit(d)
        if norm is not None:
            digits.append(norm)
    sign_from_ssm = value.get("sign_from_ssm") or {}
    sfs: Dict[str, int] = {}
    if isinstance(sign_from_ssm, dict):
        for k, v in sign_from_ssm.items():
            try:
                sfs[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    out: Dict[str, Any] = {"digits": digits}
    if sfs:
        out["sign_from_ssm"] = sfs
    if value.get("description"):
        out["description"] = str(value["description"])
    return out


def _normalize_port_overrides(value: Any) -> Dict[str, Dict[str, Any]]:
    """把 {port -> overrides} 规范化：port 强制字符串，overrides 保持浅拷贝"""
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in value.items():
        if not isinstance(v, dict):
            continue
        out[str(k)] = dict(v)
    return out


def _normalize_ssm_semantics(value: Any) -> Dict[str, str]:
    """SSM 值 → 业务语义文本。键强制字符串，值强制字符串"""
    if not isinstance(value, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in value.items():
        out[str(k)] = "" if v is None else str(v)
    return out


# 与 TSN 的 FamilyHandler 保持一致的接口


class Arinc429FamilyHandler:
    family = "arinc429"

    # ──────────────── normalize ────────────────
    def normalize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = copy.deepcopy(spec_json or {})
        meta = spec.setdefault("protocol_meta", {})
        meta.setdefault("name", "")
        meta.setdefault("version", "")
        meta.setdefault("description", "")

        labels = spec.get("labels") or []
        if not isinstance(labels, list):
            labels = []

        normalized_labels: List[Dict[str, Any]] = []
        for lab in labels:
            if not isinstance(lab, dict):
                continue
            label_oct = str(lab.get("label_oct") or "").strip()
            if not label_oct:
                # 保留原顺序但标记为空 label；validate 时报错
                normalized_labels.append(
                    {**lab, "label_oct": "", "label_dec": None}
                )
                continue
            try:
                label_dec = int(label_oct, 8)
            except (TypeError, ValueError):
                label_dec = None
            raw_discrete = lab.get("discrete_bits") or {}
            discrete_bits: Dict[str, Any] = {}
            if isinstance(raw_discrete, dict):
                for k, v in raw_discrete.items():
                    discrete_bits[str(k)] = _normalize_discrete_bit_value(v)

            bit_groups: List[Dict[str, Any]] = []
            for item in lab.get("discrete_bit_groups") or []:
                norm = _normalize_bit_group(item)
                if norm is not None:
                    bit_groups.append(norm)

            bnr_fields: List[Dict[str, Any]] = []
            for item in lab.get("bnr_fields") or []:
                norm = _normalize_bnr_field(item)
                if norm is not None:
                    bnr_fields.append(norm)

            special_fields: List[Dict[str, Any]] = []
            for item in lab.get("special_fields") or []:
                norm = _normalize_special_field(item)
                if norm is not None:
                    special_fields.append(norm)

            bcd_pattern = _normalize_bcd_pattern(lab.get("bcd_pattern"))
            port_overrides = _normalize_port_overrides(lab.get("port_overrides"))
            ssm_semantics = _normalize_ssm_semantics(lab.get("ssm_semantics"))

            new_lab = {
                "label_oct": label_oct,
                "label_dec": label_dec,
                "name": str(lab.get("name") or "").strip() or "Unknown",
                "cn": str(lab.get("cn") or "").strip(),
                "direction": lab.get("direction") or "",
                "sources": list(lab.get("sources") or []),
                "sdi": lab.get("sdi"),
                "ssm_type": lab.get("ssm_type") or "bnr",
                "data_type": lab.get("data_type"),
                "unit": lab.get("unit"),
                "range_desc": lab.get("range_desc"),
                "resolution": lab.get("resolution"),
                "reserved_bits": lab.get("reserved_bits"),
                "notes": lab.get("notes"),
                "discrete_bits": discrete_bits,
                "discrete_bit_groups": bit_groups,
                "special_fields": special_fields,
                "bnr_fields": bnr_fields,
                "bcd_pattern": bcd_pattern,
                "port_overrides": port_overrides,
                "ssm_semantics": ssm_semantics,
            }
            normalized_labels.append(new_lab)

        normalized_labels.sort(
            key=lambda x: (x.get("label_dec") if x.get("label_dec") is not None else 9999, x.get("label_oct") or "")
        )
        spec["labels"] = normalized_labels
        # port_routing 归属 TSN 网络配置，静默丢弃遗留字段（若存在）
        spec.pop("port_routing", None)
        return spec

    # ──────────────── validate ────────────────
    def validate_spec(self, spec_json: Dict[str, Any]) -> SpecValidation:
        out = SpecValidation()
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        if not meta.get("name"):
            out.errors.append("protocol_meta.name 不能为空")
        if not meta.get("version"):
            out.errors.append("protocol_meta.version 不能为空")

        labels = spec.get("labels") or []
        if not isinstance(labels, list):
            out.errors.append("labels 必须是数组")
            return out
        if not labels:
            out.warnings.append("labels 为空，当前设备无任何 Label 定义")

        seen_octs: set[str] = set()
        for idx, lab in enumerate(labels):
            prefix = f"labels[{idx}]"
            if not isinstance(lab, dict):
                out.errors.append(f"{prefix} 必须是对象")
                continue
            oct_val = str(lab.get("label_oct") or "").strip()
            if not oct_val:
                out.errors.append(f"{prefix}: label_oct 不能为空")
            else:
                try:
                    n = int(oct_val, 8)
                    if n > 255:
                        out.errors.append(
                            f"{prefix}: label_oct='{oct_val}' 超出范围（最大 377）"
                        )
                except (TypeError, ValueError):
                    out.errors.append(
                        f"{prefix}: label_oct='{oct_val}' 不是合法八进制"
                    )
                if oct_val in seen_octs:
                    out.errors.append(f"{prefix}: label_oct='{oct_val}' 重复")
                seen_octs.add(oct_val)

            if not lab.get("name"):
                out.errors.append(f"{prefix}: name 不能为空")

            ssm_type = lab.get("ssm_type")
            if ssm_type and ssm_type not in _SSM_TYPES:
                out.warnings.append(
                    f"{prefix}: ssm_type={ssm_type!r} 不在推荐值域 {sorted(_SSM_TYPES)}"
                )

            for j, bf in enumerate(lab.get("bnr_fields") or []):
                bp = f"{prefix}.bnr_fields[{j}]"
                if not isinstance(bf, dict):
                    out.errors.append(f"{bp} 必须是对象")
                    continue
                if not bf.get("name"):
                    out.errors.append(f"{bp}: name 不能为空")
                data_bits = bf.get("data_bits")
                if not (isinstance(data_bits, (list, tuple)) and len(data_bits) == 2):
                    out.errors.append(f"{bp}: data_bits 必须是 [起始位, 结束位]")
                sign_style = bf.get("sign_style")
                if sign_style and sign_style not in _SIGN_STYLES:
                    out.errors.append(
                        f"{bp}: sign_style={sign_style!r} 不合法，仅允许 {sorted(_SIGN_STYLES)}"
                    )

            for j, sf in enumerate(lab.get("special_fields") or []):
                sp = f"{prefix}.special_fields[{j}]"
                if not isinstance(sf, dict):
                    out.errors.append(f"{sp} 必须是对象")
                    continue
                if not sf.get("name"):
                    out.errors.append(f"{sp}: name 不能为空")
                # 兼容 `bits` 与 `data_bits` 两种老/新写法
                bits = sf.get("data_bits") if "data_bits" in sf else sf.get("bits")
                encoding = sf.get("encoding") or sf.get("type") or ""
                if encoding in _WHOLE_WORD_SPECIAL_ENCODINGS and bits is None:
                    # hex/raw/word：整 word 原始值，允许不带 bits
                    continue
                if not (isinstance(bits, (list, tuple)) and len(bits) == 2):
                    out.errors.append(f"{sp}: data_bits 必须是 [起始位, 结束位]")

            for bit_key, desc in (lab.get("discrete_bits") or {}).items():
                dp = f"{prefix}.discrete_bits[{bit_key}]"
                try:
                    b = int(bit_key)
                    if b < 1 or b > 32:
                        out.errors.append(f"{dp}: bit 序号必须在 1..32 之间")
                except (TypeError, ValueError):
                    out.errors.append(f"{dp}: bit 序号必须为整数")
                if isinstance(desc, dict) and not desc.get("name"):
                    out.errors.append(f"{dp}: 结构化描述缺少 name 字段")

            for j, grp in enumerate(lab.get("discrete_bit_groups") or []):
                gp = f"{prefix}.discrete_bit_groups[{j}]"
                if not isinstance(grp, dict):
                    out.errors.append(f"{gp} 必须是对象")
                    continue
                if not grp.get("name"):
                    out.errors.append(f"{gp}: name 不能为空")
                bits = grp.get("bits")
                if not (isinstance(bits, (list, tuple)) and len(bits) == 2):
                    out.errors.append(f"{gp}: bits 必须是 [起始位, 结束位]")
                else:
                    try:
                        a, b2 = int(bits[0]), int(bits[1])
                        if not (1 <= a <= 32 and 1 <= b2 <= 32):
                            out.errors.append(
                                f"{gp}: bits 范围必须在 1..32 之间"
                            )
                        if a > b2:
                            out.errors.append(
                                f"{gp}: bits 起始位不能大于结束位"
                            )
                    except (TypeError, ValueError):
                        out.errors.append(f"{gp}: bits 必须是整数")

            bcd_pattern = lab.get("bcd_pattern")
            if bcd_pattern:
                if not isinstance(bcd_pattern, dict):
                    out.errors.append(f"{prefix}.bcd_pattern 必须是对象")
                else:
                    digits = bcd_pattern.get("digits") or []
                    if not isinstance(digits, list) or not digits:
                        out.errors.append(
                            f"{prefix}.bcd_pattern.digits 不能为空"
                        )
                    for k, d in enumerate(digits if isinstance(digits, list) else []):
                        dpth = f"{prefix}.bcd_pattern.digits[{k}]"
                        if not isinstance(d, dict):
                            out.errors.append(f"{dpth} 必须是对象")
                            continue
                        if not d.get("name"):
                            out.errors.append(f"{dpth}: name 不能为空")
                        db = d.get("data_bits")
                        if not (
                            isinstance(db, (list, tuple)) and len(db) == 2
                        ):
                            out.errors.append(
                                f"{dpth}: data_bits 必须是 [起始位, 结束位]"
                            )

            port_overrides = lab.get("port_overrides") or {}
            if port_overrides and not isinstance(port_overrides, dict):
                out.errors.append(f"{prefix}.port_overrides 必须是对象")
            else:
                for port, ov in port_overrides.items():
                    popth = f"{prefix}.port_overrides[{port}]"
                    if not isinstance(ov, dict):
                        out.errors.append(f"{popth} 必须是对象")
                        continue
                    try:
                        p = int(port)
                        if not (0 < p < 65536):
                            out.warnings.append(
                                f"{popth}: port={port} 超出 UDP 端口范围"
                            )
                    except (TypeError, ValueError):
                        out.warnings.append(f"{popth}: port 应为整数字符串")

        # 注：port_routing 归属 TSN 网络配置（BundlePort.arinc_labels），
        # 此处不再参与设备 ICD 的校验。

        # ─── Phase 4 扩展：ssm_type 语义 / discrete values 完备性 ───
        # 在 bundle-driven 模式下（见 Arinc429Mixin._decode_with_bundle），
        # 解析器严重依赖以下不变式；这里先在"发布/审批前"拦住。
        self._validate_ssm_semantics(labels, out)
        return out

    def _validate_ssm_semantics(
        self, labels: List[Dict[str, Any]], out: SpecValidation
    ) -> None:
        """校验 ssm_type 与子字段的必填性 / 枚举完备性。"""
        for idx, lab in enumerate(labels):
            if not isinstance(lab, dict):
                continue
            prefix = f"labels[{idx}]"
            ssm_type = str(lab.get("ssm_type") or "").lower()
            bnr_fields = lab.get("bnr_fields") or []
            disc_bits = lab.get("discrete_bits") or {}
            disc_groups = lab.get("discrete_bit_groups") or []
            bcd_pattern = lab.get("bcd_pattern") or {}
            special_fields = lab.get("special_fields") or []

            if ssm_type == "bnr":
                if not bnr_fields:
                    out.errors.append(
                        f"{prefix}: ssm_type='bnr' 但 bnr_fields 为空"
                    )
            elif ssm_type == "discrete":
                if not disc_bits and not disc_groups:
                    out.errors.append(
                        f"{prefix}: ssm_type='discrete' 但 discrete_bits 与 "
                        "discrete_bit_groups 均为空"
                    )
            elif ssm_type == "bcd":
                digits = (bcd_pattern or {}).get("digits") or []
                if not digits:
                    out.errors.append(
                        f"{prefix}: ssm_type='bcd' 但 bcd_pattern.digits 为空"
                    )
            elif ssm_type == "special" and not special_fields and not bnr_fields:
                out.warnings.append(
                    f"{prefix}: ssm_type='special' 但既无 special_fields 也无 bnr_fields"
                )

            # discrete_bits values 完备性：单 bit 推荐同时填 "0" / "1"；否则给 warning
            for bit_key, desc in disc_bits.items():
                if not isinstance(desc, dict):
                    continue
                values = desc.get("values") or {}
                if values and isinstance(values, dict):
                    keys = set(str(k) for k in values.keys())
                    if keys and keys != {"0", "1"} and not bool(desc.get("incomplete")):
                        missing = {"0", "1"} - keys
                        if missing:
                            out.warnings.append(
                                f"{prefix}.discrete_bits[{bit_key}].values 缺少 "
                                f"{sorted(missing)} 键；如属有意设计请标注 "
                                "incomplete=true"
                            )

            # discrete_bit_groups values 完备性：推荐覆盖 2^nbits 范围
            for j, grp in enumerate(disc_groups):
                if not isinstance(grp, dict):
                    continue
                bits = grp.get("bits") or []
                values = grp.get("values") or {}
                if (
                    values
                    and isinstance(values, dict)
                    and isinstance(bits, (list, tuple))
                    and len(bits) == 2
                ):
                    try:
                        a, b2 = int(bits[0]), int(bits[1])
                        nbits = abs(b2 - a) + 1
                        if (
                            nbits <= 4
                            and not bool(grp.get("incomplete"))
                            and len(values) < (1 << nbits)
                        ):
                            out.warnings.append(
                                f"{prefix}.discrete_bit_groups[{j}] {nbits}-bit 但 "
                                f"values 只覆盖 {len(values)}/"
                                f"{1 << nbits}；如属有意设计请标注 incomplete=true"
                            )
                    except (TypeError, ValueError):
                        pass

            # BCD digits 合法性：weight 必填、mask 需为 0x** 字符串
            digits = (bcd_pattern or {}).get("digits") or []
            if isinstance(digits, list):
                for k, d in enumerate(digits):
                    if not isinstance(d, dict):
                        continue
                    dpth = f"{prefix}.bcd_pattern.digits[{k}]"
                    if "weight" not in d:
                        out.warnings.append(f"{dpth}: 未声明 weight，默认按 1 处理")
                    mask = d.get("mask")
                    if mask is not None and not isinstance(mask, str):
                        out.warnings.append(
                            f"{dpth}: mask 建议写成 '0x07' 形式字符串"
                        )

    # ──────────────── diff ────────────────
    def diff_spec(
        self, old: Dict[str, Any] | None, new: Dict[str, Any]
    ) -> SpecDiff:
        out = SpecDiff()
        new_norm = self.normalize_spec(new or {})
        new_labels = {l["label_oct"]: l for l in new_norm.get("labels", []) if l.get("label_oct")}

        old_labels: Dict[str, Dict[str, Any]] = {}
        if old:
            old_norm = self.normalize_spec(old)
            old_labels = {l["label_oct"]: l for l in old_norm.get("labels", []) if l.get("label_oct")}

            old_meta = old_norm.get("protocol_meta") or {}
            new_meta = new_norm.get("protocol_meta") or {}
            for key in ("name", "version", "description"):
                ov = old_meta.get(key)
                nv = new_meta.get(key)
                if (ov or None) != (nv or None):
                    out.meta_changed[key] = {"old": ov, "new": nv}
            # 注：port_routing 归 TSN 网络配置，不参与设备 ICD 的 diff
        else:
            # 全量新增
            for oct_, lab in new_labels.items():
                out.items_added.append(
                    {"key": oct_, "label_oct": oct_, "name": lab.get("name")}
                )
            return out

        for oct_, new_lab in new_labels.items():
            if oct_ not in old_labels:
                out.items_added.append(
                    {"key": oct_, "label_oct": oct_, "name": new_lab.get("name")}
                )
                continue
            old_lab = old_labels[oct_]
            changes = self._label_diff(old_lab, new_lab)
            if changes:
                out.items_changed.append(
                    {
                        "key": oct_,
                        "label_oct": oct_,
                        "name": new_lab.get("name"),
                        "changes": changes,
                    }
                )

        for oct_, old_lab in old_labels.items():
            if oct_ not in new_labels:
                out.items_removed.append(
                    {"key": oct_, "label_oct": oct_, "name": old_lab.get("name")}
                )
        return out

    @staticmethod
    def _label_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        changed: Dict[str, Dict[str, Any]] = {}
        scalar_keys = (
            "name",
            "direction",
            "sdi",
            "ssm_type",
            "data_type",
            "unit",
            "range_desc",
            "resolution",
            "reserved_bits",
            "notes",
        )
        for k in scalar_keys:
            ov = old.get(k)
            nv = new.get(k)
            if (ov if ov is not None else None) != (nv if nv is not None else None):
                changed[k] = {"old": ov, "new": nv}

        for k in (
            "sources",
            "discrete_bits",
            "discrete_bit_groups",
            "special_fields",
            "bnr_fields",
            "bcd_pattern",
            "port_overrides",
            "ssm_semantics",
        ):
            ov = old.get(k)
            nv = new.get(k)
            if ov != nv:
                changed[k] = {"old": ov, "new": nv}
        return changed

    # ──────────────── summarize / view / empty ────────────────
    def summarize_spec(self, spec_json: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec_json or {}
        meta = spec.get("protocol_meta") or {}
        labels = spec.get("labels") or []
        discrete_cnt = sum(len(l.get("discrete_bits") or {}) for l in labels if isinstance(l, dict))
        bit_group_cnt = sum(
            len(l.get("discrete_bit_groups") or []) for l in labels if isinstance(l, dict)
        )
        special_cnt = sum(len(l.get("special_fields") or []) for l in labels if isinstance(l, dict))
        bnr_cnt = sum(len(l.get("bnr_fields") or []) for l in labels if isinstance(l, dict))
        bcd_pattern_cnt = sum(
            1 for l in labels if isinstance(l, dict) and l.get("bcd_pattern")
        )
        port_override_cnt = sum(
            len(l.get("port_overrides") or {}) for l in labels if isinstance(l, dict)
        )
        return {
            "family": self.family,
            "name": meta.get("name"),
            "version": meta.get("version"),
            "label_count": len(labels),
            "discrete_bit_count": discrete_cnt,
            "discrete_bit_group_count": bit_group_cnt,
            "special_field_count": special_cnt,
            "bnr_field_count": bnr_cnt,
            "bcd_pattern_count": bcd_pattern_cnt,
            "port_override_count": port_override_cnt,
        }

    def labels_view(self, spec_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self.normalize_spec(spec_json or {})
        return [
            {
                "key": l.get("label_oct"),
                "label_oct": l.get("label_oct"),
                "label_dec": l.get("label_dec"),
                "name": l.get("name"),
                "direction": l.get("direction"),
                "data_type": l.get("data_type"),
                "unit": l.get("unit"),
                "discrete_count": len(l.get("discrete_bits") or {}),
                "special_count": len(l.get("special_fields") or []),
                "bnr_count": len(l.get("bnr_fields") or []),
            }
            for l in spec.get("labels", [])
            if l.get("label_oct")
        ]

    def new_empty_spec(
        self,
        *,
        device_name: str,
        version_name: str,
        description: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "protocol_meta": {
                "name": device_name,
                "version": version_name,
                "description": description or "",
            },
            "labels": [],
        }
