# -*- coding: utf-8 -*-
"""TSN 协议草稿静态校验（MR2）

提交审批前必过的门槛：
- `error` 阻断 submit。
- `warning` 只提示，不阻断。

校验粒度只看当前 Draft 的端口/字段本身，不触碰 pcap 实际流量（留到后续迭代）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    DraftFieldDefinition,
    DraftPortDefinition,
    ParserProfile,
    ProtocolVersionDraft,
)
from .protocol_draft_service import VALID_DATA_DIRECTIONS, VALID_DATA_TYPES
from .protocol_service import PORT_FAMILY_MAP, resolve_port_family
from .parsers import ParserRegistry


async def _known_families(db: AsyncSession) -> set[str]:
    fams = set()
    res = await db.execute(
        select(ParserProfile).where(ParserProfile.is_active.is_(True))
    )
    for pp in res.scalars().all():
        fam = (pp.protocol_family or "").strip()
        if fam:
            fams.add(fam)
    fams.update(v for v in PORT_FAMILY_MAP.values() if v)
    return fams


def _make_issue(
    severity: str,
    code: str,
    message: str,
    *,
    port_number: Optional[int] = None,
    field_name: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    item = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if port_number is not None:
        item["port_number"] = port_number
    if field_name is not None:
        item["field_name"] = field_name
    if extra:
        item["extra"] = extra
    return item


async def run_static_check(
    db: AsyncSession, draft_id: int
) -> Dict[str, Any]:
    """对草稿跑静态校验。返回 {errors: [...], warnings: [...], summary: {...}}"""
    res = await db.execute(
        select(ProtocolVersionDraft)
        .where(ProtocolVersionDraft.id == draft_id)
        .options(
            selectinload(ProtocolVersionDraft.ports).selectinload(DraftPortDefinition.fields)
        )
    )
    draft: Optional[ProtocolVersionDraft] = res.scalar_one_or_none()
    if not draft:
        raise ValueError(f"草稿 {draft_id} 不存在")

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    known_fams = await _known_families(db)
    registry_keys = set(ParserRegistry.list_parsers())

    # 1) Draft 层：至少一个端口
    if not draft.ports:
        errors.append(_make_issue(
            "error", "EMPTY_DRAFT",
            "草稿没有任何端口，无法提交",
        ))

    # 2) 端口层检查
    seen_port_numbers: Dict[int, int] = {}
    for p in draft.ports:
        if p.port_number is None:
            errors.append(_make_issue(
                "error", "PORT_NUMBER_REQUIRED",
                "端口号必填",
                port_number=p.port_number,
            ))
            continue

        # 端口号允许重复（同一 port_number 可有多个 message_name / direction）
        if p.port_number in seen_port_numbers:
            warnings.append(_make_issue(
                "warning", "DUPLICATE_PORT",
                f"端口号 {p.port_number} 在草稿内多次出现（真实 ICD 中允许，如同端口承载多种消息）",
                port_number=p.port_number,
            ))
        seen_port_numbers[p.port_number] = p.id

        if not p.message_name or not str(p.message_name).strip():
            errors.append(_make_issue(
                "error", "PORT_MESSAGE_NAME_REQUIRED",
                "端口的消息名称必填",
                port_number=p.port_number,
            ))
        direction = (p.data_direction or "").lower()
        if direction not in VALID_DATA_DIRECTIONS:
            errors.append(_make_issue(
                "error", "PORT_DIRECTION_INVALID",
                f"端口方向必须为 {sorted(VALID_DATA_DIRECTIONS)} 之一，当前为 {p.data_direction!r}",
                port_number=p.port_number,
            ))
        else:
            if direction == "uplink" and not (p.source_device or "").strip():
                warnings.append(_make_issue(
                    "warning", "UPLINK_MISSING_SOURCE",
                    "上行端口缺少 source_device",
                    port_number=p.port_number,
                ))
            if direction == "downlink" and not (p.target_device or "").strip():
                warnings.append(_make_issue(
                    "warning", "DOWNLINK_MISSING_TARGET",
                    "下行端口缺少 target_device",
                    port_number=p.port_number,
                ))

        if p.period_ms is None or (isinstance(p.period_ms, (int, float)) and p.period_ms <= 0):
            warnings.append(_make_issue(
                "warning", "PORT_PERIOD_INVALID",
                "端口周期 period_ms 未填或 ≤ 0",
                port_number=p.port_number,
            ))

        fam = (p.protocol_family or "").strip()
        resolved_fam = resolve_port_family(p.port_number, db_family=fam)
        if not resolved_fam:
            warnings.append(_make_issue(
                "warning", "PORT_FAMILY_UNKNOWN",
                "端口未指定协议族且 PORT_FAMILY_MAP 无兜底；激活闸门（MR3）会拦截",
                port_number=p.port_number,
            ))
        elif resolved_fam not in known_fams:
            warnings.append(_make_issue(
                "warning", "PORT_FAMILY_UNREGISTERED",
                f"协议族 {resolved_fam!r} 未在当前后端注册的解析器族中（parser_profiles 活跃列表 + PORT_FAMILY_MAP 的并集）",
                port_number=p.port_number,
                extra={"family": resolved_fam},
            ))

        # 3) 字段层检查
        fields = sorted(p.fields or [], key=lambda x: (x.field_offset or 0))
        if not fields:
            warnings.append(_make_issue(
                "warning", "PORT_NO_FIELDS",
                "端口暂无字段，数据解析将无法输出结构化字段",
                port_number=p.port_number,
            ))
        seen_field_names: Dict[str, int] = {}
        prev_end: Optional[int] = None
        prev_name: Optional[str] = None
        for f in fields:
            _check_field(f, p.port_number, errors, warnings, seen_field_names)

            # 区间重叠
            if f.field_offset is not None and f.field_length is not None and f.field_length > 0:
                start = f.field_offset
                end = f.field_offset + f.field_length
                if prev_end is not None and start < prev_end:
                    errors.append(_make_issue(
                        "error", "FIELD_OVERLAP",
                        f"字段 {f.field_name!r} 与前一字段 {prev_name!r} 区间重叠",
                        port_number=p.port_number,
                        field_name=f.field_name,
                        extra={"this_range": [start, end], "prev_end": prev_end},
                    ))
                prev_end = max(prev_end or end, end)
                prev_name = f.field_name

    summary = {
        "port_count": len(draft.ports),
        "field_count": sum(len(p.fields or []) for p in draft.ports),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "can_submit": len(errors) == 0,
    }
    return {"errors": errors, "warnings": warnings, "summary": summary}


def _check_field(
    f: DraftFieldDefinition,
    port_number: int,
    errors: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    seen_field_names: Dict[str, int],
):
    if not f.field_name or not str(f.field_name).strip():
        errors.append(_make_issue(
            "error", "FIELD_NAME_REQUIRED",
            "字段名必填",
            port_number=port_number,
        ))
    else:
        if f.field_name in seen_field_names:
            warnings.append(_make_issue(
                "warning", "FIELD_NAME_DUPLICATE",
                f"字段名 {f.field_name!r} 在端口 {port_number} 重复（真实 ICD 中允许重复，如\"保留\"字段）",
                port_number=port_number,
                field_name=f.field_name,
            ))
        seen_field_names[f.field_name] = f.id
    if f.field_offset is None or f.field_offset < 0:
        errors.append(_make_issue(
            "error", "FIELD_OFFSET_INVALID",
            "字段偏移需 ≥ 0",
            port_number=port_number,
            field_name=f.field_name,
        ))
    if f.field_length is None or f.field_length <= 0:
        errors.append(_make_issue(
            "error", "FIELD_LENGTH_INVALID",
            "字段长度需 > 0",
            port_number=port_number,
            field_name=f.field_name,
        ))
    dt = (f.data_type or "").strip()
    if dt and dt not in VALID_DATA_TYPES:
        errors.append(_make_issue(
            "error", "FIELD_DATATYPE_INVALID",
            f"字段数据类型 {dt!r} 不在白名单 {sorted(VALID_DATA_TYPES)} 中",
            port_number=port_number,
            field_name=f.field_name,
        ))
    bo = (f.byte_order or "").strip().lower()
    if bo and bo not in {"big", "little"}:
        warnings.append(_make_issue(
            "warning", "FIELD_BYTEORDER_UNKNOWN",
            f"字节序 {bo!r} 非 big/little",
            port_number=port_number,
            field_name=f.field_name,
        ))
