# -*- coding: utf-8 -*-
"""TSN 协议版本激活闸门（MR3）

职责：
1. `generate_port_registry(db, version_id)` —— 根据指定版本的 PortDefinition 生成
   `backend/app/services/generated/port_registry.py`，内含 FAMILY_PORTS /
   PORT_TO_FAMILY / PORT_FIELD_SIGNATURES 三张字典。原子写，可被 importlib.reload。

2. `analyze_readiness(db, version_id)` —— 对比当前版本与同协议下"上一可用版本"，
   把变更分档（green / yellow / red）生成 ActivationReport JSON，直接写回
   `ProtocolVersion.activation_report_json`。

3. `activate_version(db, version_id, user, force, reason)` —— 把 PendingCode 切换到
   Available。红项必须 force=True + 填写 reason。记录审计字段 + 通知相关角色。

设计取向：
- 仅限 TSN 层（PortDefinition / FieldDefinition / protocol_family），不改设备 parser。
- generated/*.py 是 opt-in 的辅助表。老 parser 保持 supported_ports 不变 → 不受影响。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_DEPRECATED,
    AVAILABILITY_PENDING_CODE,
    FieldDefinition,
    NOTIFICATION_KIND_CR_PUBLISHED,
    ParserProfile,
    PortDefinition,
    ProtocolVersion,
    User,
)
from ..permissions import ROLE_ADMIN, ROLE_NETWORK_TEAM
from .bundle import generator as bundle_generator
from .notification_service import notify_usernames, notify_users_by_role
from .parsers import ParserRegistry
from .protocol_service import PORT_FAMILY_MAP, resolve_port_family


# ══════════════════════════════════════════════════════════════════════
# 路径常量
# ══════════════════════════════════════════════════════════════════════

_SERVICES_DIR = Path(__file__).resolve().parent
_GENERATED_DIR = _SERVICES_DIR / "generated"
_PORT_REGISTRY_PATH = _GENERATED_DIR / "port_registry.py"

# 供前端/调用方使用的相对路径（相对于仓库根的展示用，不做路径解析）
_PORT_REGISTRY_REL = "backend/app/services/generated/port_registry.py"


def _atomic_write_text(path: Path, content: str) -> None:
    """同目录下 .tmp 再 rename，避免半成品文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════
# 代码生成：port_registry.py
# ══════════════════════════════════════════════════════════════════════

_PY_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _py_repr_key(s: str) -> str:
    """对字典 key 安全地用 repr，保持可读性。"""
    return repr(s)


async def _load_version_with_ports(db: AsyncSession, version_id: int) -> ProtocolVersion:
    res = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.id == version_id)
        .options(
            selectinload(ProtocolVersion.protocol),
            selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields),
        )
    )
    pv = res.scalar_one_or_none()
    if not pv:
        raise HTTPException(status_code=404, detail=f"协议版本 {version_id} 不存在")
    return pv


def _render_port_registry_source(
    *,
    version_id: int,
    version_label: str,
    protocol_name: Optional[str],
    generated_at: datetime,
    family_ports: Dict[str, List[int]],
    port_to_family: Dict[int, str],
    port_field_signatures: Dict[int, Tuple[Tuple[str, int, int, str], ...]],
) -> str:
    """把输入数据渲染成 port_registry.py 源码字符串。"""
    lines: List[str] = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('"""AUTO-GENERATED — DO NOT HAND-EDIT.')
    lines.append("")
    lines.append(f"source_version_id: {version_id}")
    lines.append(f"source_protocol: {protocol_name or '-'}")
    lines.append(f"source_version: {version_label}")
    lines.append(f"generated_at: {generated_at.isoformat()}Z")
    lines.append("")
    lines.append("由 protocol_activation_service.generate_port_registry 生成，")
    lines.append("每次 TSN 协议版本发布到 PendingCode 时覆盖。")
    lines.append('"""')
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("# family -> 按端口号排序的端口列表")
    lines.append("FAMILY_PORTS: dict[str, list[int]] = {")
    for fam in sorted(family_ports.keys()):
        ports_sorted = sorted(set(family_ports[fam]))
        ports_literal = ", ".join(str(p) for p in ports_sorted)
        lines.append(f"    {_py_repr_key(fam)}: [{ports_literal}],")
    lines.append("}")
    lines.append("")
    lines.append("# port -> family（DB 优先，未在 DB 标注的由 PORT_FAMILY_MAP 兜底）")
    lines.append("PORT_TO_FAMILY: dict[int, str] = {")
    for port in sorted(port_to_family.keys()):
        lines.append(f"    {port}: {_py_repr_key(port_to_family[port])},")
    lines.append("}")
    lines.append("")
    lines.append("# port -> tuple((field_name, offset, length, data_type), ...)")
    lines.append("PORT_FIELD_SIGNATURES: dict[int, tuple] = {")
    for port in sorted(port_field_signatures.keys()):
        sig = port_field_signatures[port]
        if not sig:
            lines.append(f"    {port}: (),")
            continue
        lines.append(f"    {port}: (")
        for (fname, offset, length, dtype) in sig:
            lines.append(
                f"        ({_py_repr_key(fname)}, {offset}, {length}, {_py_repr_key(dtype)}),"
            )
        lines.append("    ),")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


async def generate_port_registry(db: AsyncSession, version_id: int) -> Dict[str, Any]:
    """根据 version_id 的端口/字段定义生成 generated/port_registry.py。

    返回 artifact 元数据：{path, relative_path, sha256, bytes_written, generated_at}
    """
    pv = await _load_version_with_ports(db, version_id)

    family_ports: Dict[str, List[int]] = {}
    port_to_family: Dict[int, str] = {}
    port_field_signatures: Dict[int, Tuple[Tuple[str, int, int, str], ...]] = {}

    for port in pv.ports or []:
        fam = resolve_port_family(port.port_number, db_family=port.protocol_family)
        if fam:
            family_ports.setdefault(fam, []).append(port.port_number)
            port_to_family[port.port_number] = fam
        sig_items: List[Tuple[str, int, int, str]] = []
        for f in sorted(port.fields or [], key=lambda x: (x.field_offset or 0, x.field_name or "")):
            sig_items.append(
                (
                    f.field_name or "",
                    int(f.field_offset or 0),
                    int(f.field_length or 0),
                    (f.data_type or "bytes"),
                )
            )
        port_field_signatures[port.port_number] = tuple(sig_items)

    generated_at = datetime.utcnow()
    source = _render_port_registry_source(
        version_id=pv.id,
        version_label=pv.version or "",
        protocol_name=pv.protocol.name if pv.protocol else None,
        generated_at=generated_at,
        family_ports=family_ports,
        port_to_family=port_to_family,
        port_field_signatures=port_field_signatures,
    )
    sha256 = _sha256_text(source)

    _atomic_write_text(_PORT_REGISTRY_PATH, source)

    return {
        "path": _PORT_REGISTRY_REL,
        "abs_path": str(_PORT_REGISTRY_PATH),
        "sha256": sha256,
        "bytes_written": len(source.encode("utf-8")),
        "generated_at": generated_at.isoformat() + "Z",
        "stats": {
            "families": len(family_ports),
            "ports_with_family": len(port_to_family),
            "ports_with_signature": len(port_field_signatures),
        },
    }


def _reload_port_registry() -> None:
    """强制重载 generated.port_registry 以便 analyze_readiness 读取最新内容。"""
    try:
        import app.services.generated.port_registry as _pr  # type: ignore
        importlib.reload(_pr)
    except Exception:
        # 首次生成前模块不存在；首次 import 会在 BaseParser 回落逻辑里按需加载
        try:
            import importlib as _il
            _il.invalidate_caches()
            __import__("app.services.generated.port_registry")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
# 就绪度体检（analyze_readiness）
# ══════════════════════════════════════════════════════════════════════

# 字段语义属性：改动这些会触发 yellow（二进制解读可能变）
_SEMANTIC_FIELD_ATTRS = ("data_type", "byte_order", "field_offset", "field_length")
# 字段派生属性：改动只影响展示，不影响解析正确性
_COSMETIC_FIELD_ATTRS = ("scale_factor", "unit", "description")


async def _find_previous_available_version(
    db: AsyncSession, current: ProtocolVersion
) -> Optional[ProtocolVersion]:
    """找同 protocol_id 下、created_at 早于 current 且处于 Available 状态的最新版本。"""
    res = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.protocol_id == current.protocol_id)
        .where(ProtocolVersion.id != current.id)
        .where(ProtocolVersion.availability_status == AVAILABILITY_AVAILABLE)
        .options(
            selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields),
        )
        .order_by(ProtocolVersion.created_at.desc())
    )
    versions = list(res.scalars().all())
    if not versions:
        return None
    # 优先选 created_at 比 current 早的；如果全都晚于 current，也拿最新的兜底
    older = [v for v in versions if (v.created_at or datetime.min) <= (current.created_at or datetime.min)]
    return older[0] if older else versions[0]


async def _list_active_profiles_by_family(db: AsyncSession) -> Dict[str, List[ParserProfile]]:
    res = await db.execute(
        select(ParserProfile).where(ParserProfile.is_active.is_(True))
    )
    profiles = list(res.scalars().all())
    by_fam: Dict[str, List[ParserProfile]] = {}
    for pp in profiles:
        fam = (pp.protocol_family or "").strip()
        if not fam:
            continue
        by_fam.setdefault(fam, []).append(pp)
    return by_fam


def _family_has_registered_parser(
    family: str, profiles_by_family: Dict[str, List[ParserProfile]]
) -> Tuple[bool, List[str]]:
    """判断 family 是否至少有一个 ParserProfile 的 parser_key 在 ParserRegistry 里注册。

    返回 (是否 OK, 匹配到的 parser_key 列表)
    """
    candidates = [p.parser_key for p in profiles_by_family.get(family, []) if p.parser_key]
    registry_keys = set(ParserRegistry.list_parsers())
    matched = [k for k in candidates if k in registry_keys]
    return (bool(matched), matched)


def _probe_can_parse_port(parser_keys: List[str], port: int) -> Tuple[bool, List[str]]:
    """对 parser_keys 列表中的每个 parser 实例化并调用 can_parse_port，
    只要任一返回 True 即视为可解析。返回 (是否 OK, 已试过但返回 False 的 key 列表)
    """
    failures: List[str] = []
    for key in parser_keys:
        parser_cls = ParserRegistry.get(key)
        if not parser_cls:
            continue
        try:
            inst = parser_cls()
            if inst.can_parse_port(port):
                return True, []
            failures.append(key)
        except Exception:
            failures.append(key)
            continue
    return False, failures


def _snapshot_field(f: Any) -> Dict[str, Any]:
    return {
        "field_name": f.field_name,
        "field_offset": f.field_offset,
        "field_length": f.field_length,
        "data_type": f.data_type,
        "byte_order": f.byte_order,
        "scale_factor": f.scale_factor,
        "unit": f.unit,
    }


def _diff_port_fields(
    base_port: PortDefinition, new_port: PortDefinition
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """返回 (fields_added, fields_removed, fields_changed)"""
    base_map = {f.field_name: f for f in (base_port.fields or [])}
    new_map = {f.field_name: f for f in (new_port.fields or [])}
    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []
    for name, nf in new_map.items():
        if name not in base_map:
            added.append(_snapshot_field(nf))
            continue
        bf = base_map[name]
        diffs: Dict[str, Tuple[Any, Any]] = {}
        for attr in _SEMANTIC_FIELD_ATTRS + _COSMETIC_FIELD_ATTRS:
            b = getattr(bf, attr, None)
            n = getattr(nf, attr, None)
            if (b if b not in ("",) else None) != (n if n not in ("",) else None):
                diffs[attr] = (b, n)
        if diffs:
            changed.append({"field_name": name, "changes": diffs})
    for name, bf in base_map.items():
        if name not in new_map:
            removed.append(_snapshot_field(bf))
    return added, removed, changed


async def analyze_readiness(db: AsyncSession, version_id: int) -> Dict[str, Any]:
    """对 version_id 生成就绪度体检报告并写回 ProtocolVersion.activation_report_json。"""
    current = await _load_version_with_ports(db, version_id)
    previous = await _find_previous_available_version(db, current)

    profiles_by_family = await _list_active_profiles_by_family(db)
    _reload_port_registry()

    current_ports_by_num = {p.port_number: p for p in (current.ports or [])}
    base_ports_by_num = {p.port_number: p for p in (previous.ports or [])} if previous else {}

    items: List[Dict[str, Any]] = []
    severity_count = {"green": 0, "yellow": 0, "red": 0}

    def _push(item: Dict[str, Any]) -> None:
        sev = item.get("severity", "green")
        severity_count[sev] = severity_count.get(sev, 0) + 1
        items.append(item)

    # ── 新增端口 ──
    for pn, p in current_ports_by_num.items():
        if pn in base_ports_by_num:
            continue
        fam = resolve_port_family(pn, db_family=p.protocol_family)
        if not fam:
            _push({
                "kind": "port_added_no_family",
                "port": pn,
                "protocol_family": None,
                "severity": "red",
                "message": f"端口 {pn} 未映射到任何协议族（PortDefinition.protocol_family 为空且不在 PORT_FAMILY_MAP 中）",
                "suggested_action": "在协议草稿中为此端口设置 protocol_family，或先由设备团队在 PORT_FAMILY_MAP 补充映射",
                "auto_fixable": False,
            })
            continue
        has_parser, matched = _family_has_registered_parser(fam, profiles_by_family)
        if not has_parser:
            _push({
                "kind": "family_has_no_parser",
                "port": pn,
                "protocol_family": fam,
                "severity": "red",
                "message": f"协议族 {fam} 没有任何 active ParserProfile 的 parser_key 已在代码中注册",
                "suggested_action": f"设备团队需先发代码 MR 注册 {fam} 的 parser 并在 ParserProfile 登记",
                "auto_fixable": False,
            })
            continue
        ok, failures = _probe_can_parse_port(matched, pn)
        if ok:
            _push({
                "kind": "port_added",
                "port": pn,
                "protocol_family": fam,
                "severity": "green",
                "message": f"端口 {pn}（{fam}）可被已注册 parser 识别",
                "matched_parser_keys": matched,
                "auto_fixable": True,
            })
        else:
            _push({
                "kind": "parser_does_not_claim_port",
                "port": pn,
                "protocol_family": fam,
                "severity": "yellow",
                "message": (
                    f"端口 {pn} 归属 {fam}，已注册 parser {matched}，但 can_parse_port 返回 False。"
                    f"端用户可能看不到该端口解析结果。"
                ),
                "suggested_action": (
                    "将此 parser 的 supported_ports 清空并声明 protocol_family 后即可 opt-in 到 generated.port_registry；"
                    "或在 parser 中显式追加该端口"
                ),
                "matched_parser_keys": matched,
                "failed_parser_keys": failures,
                "auto_fixable": False,
            })

    # ── 删除端口 ──
    for pn, bp in base_ports_by_num.items():
        if pn in current_ports_by_num:
            continue
        _push({
            "kind": "port_removed",
            "port": pn,
            "protocol_family": resolve_port_family(pn, db_family=bp.protocol_family),
            "severity": "yellow",
            "message": f"端口 {pn} 在新版本中被移除。历史解析任务若引用此端口，仍保留在旧版本中。",
            "suggested_action": "确认没有正在进行的解析流程依赖该端口",
            "auto_fixable": False,
        })

    # ── 端口字段改动 ──
    for pn, p in current_ports_by_num.items():
        if pn not in base_ports_by_num:
            continue
        bp = base_ports_by_num[pn]
        added, removed, changed = _diff_port_fields(bp, p)
        fam = resolve_port_family(pn, db_family=p.protocol_family)

        for f in added:
            _push({
                "kind": "field_added",
                "port": pn,
                "protocol_family": fam,
                "field_name": f["field_name"],
                "severity": "green",
                "message": f"端口 {pn} 新增字段 {f['field_name']}（TSN 层数据驱动，runtime 自动生效）",
                "field_snapshot": f,
                "auto_fixable": True,
            })
        for f in removed:
            _push({
                "kind": "field_removed",
                "port": pn,
                "protocol_family": fam,
                "field_name": f["field_name"],
                "severity": "yellow",
                "message": f"端口 {pn} 删除字段 {f['field_name']}。若有解析任务/事件规则引用，会缺失数据列。",
                "field_snapshot": f,
                "auto_fixable": False,
            })
        for ch in changed:
            diffs = ch["changes"]
            semantic = {k: v for k, v in diffs.items() if k in _SEMANTIC_FIELD_ATTRS}
            cosmetic = {k: v for k, v in diffs.items() if k in _COSMETIC_FIELD_ATTRS}
            if semantic:
                _push({
                    "kind": "field_semantics_change",
                    "port": pn,
                    "protocol_family": fam,
                    "field_name": ch["field_name"],
                    "severity": "yellow",
                    "message": (
                        f"端口 {pn} 字段 {ch['field_name']} 的语义属性变更："
                        + ", ".join(f"{k}:{v[0]}→{v[1]}" for k, v in semantic.items())
                    ),
                    "suggested_action": "若对应 parser 依赖硬编码 offset/length/data_type，需同步更新代码",
                    "changes": {k: {"before": v[0], "after": v[1]} for k, v in semantic.items()},
                    "auto_fixable": False,
                })
            if cosmetic:
                _push({
                    "kind": "field_cosmetic_change",
                    "port": pn,
                    "protocol_family": fam,
                    "field_name": ch["field_name"],
                    "severity": "green",
                    "message": (
                        f"端口 {pn} 字段 {ch['field_name']} 的展示属性变更（不影响解析正确性）："
                        + ", ".join(f"{k}:{v[0]}→{v[1]}" for k, v in cosmetic.items())
                    ),
                    "changes": {k: {"before": v[0], "after": v[1]} for k, v in cosmetic.items()},
                    "auto_fixable": True,
                })

    # 如果没有 previous，也要做一个"首次发布"的体检：检查 family 映射完整性
    if previous is None and not items:
        for pn, p in current_ports_by_num.items():
            fam = resolve_port_family(pn, db_family=p.protocol_family)
            if not fam:
                _push({
                    "kind": "port_no_family",
                    "port": pn,
                    "protocol_family": None,
                    "severity": "red",
                    "message": f"端口 {pn} 未映射到任何协议族",
                    "auto_fixable": False,
                })

    report = {
        "version_id": current.id,
        "base_version_id": previous.id if previous else None,
        "base_version_label": previous.version if previous else None,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "summary": severity_count,
        "items": items,
    }
    return report


# ══════════════════════════════════════════════════════════════════════
# 完整流水线：generate + analyze，写回数据库
# ══════════════════════════════════════════════════════════════════════

async def refresh_activation_pipeline(
    db: AsyncSession, version_id: int
) -> Dict[str, Any]:
    """生成 port_registry + 跑体检，把两样都写回 ProtocolVersion。

    由 publish_cr 的钩子和 refresh 端点共享。返回一个 dict：
    { report: {...}, artifacts: [{...}, ...] }

    产物列表：
    - port_registry.py 元数据（已有）
    - bundle.json 元数据（新增，MR4）
    """
    artifact = await generate_port_registry(db, version_id)

    # Bundle 生成失败不应中断激活体检，但要把错误折算成 red 项。
    bundle_artifact: Optional[Dict[str, Any]] = None
    bundle_error: Optional[str] = None
    try:
        bundle_artifact = await bundle_generator.generate_bundle(db, version_id)
    except Exception as exc:
        bundle_error = f"{type(exc).__name__}: {exc}"

    report = await analyze_readiness(db, version_id)
    if bundle_error:
        summary = report.setdefault("summary", {"green": 0, "yellow": 0, "red": 0})
        summary["red"] = int(summary.get("red") or 0) + 1
        report.setdefault("items", []).append({
            "kind": "bundle_generation_failed",
            "severity": "red",
            "message": f"bundle.json 生成失败：{bundle_error}",
            "suggested_action": "查看后端日志定位错误并修复后重跑体检",
            "auto_fixable": False,
        })

    res = await db.execute(
        select(ProtocolVersion).where(ProtocolVersion.id == version_id)
    )
    pv = res.scalar_one_or_none()
    if pv is None:
        raise HTTPException(status_code=404, detail=f"协议版本 {version_id} 不存在")
    pv.activation_report_json = json.dumps(report, ensure_ascii=False)
    pv.activation_report_generated_at = datetime.utcnow()
    artifacts = [artifact]
    if bundle_artifact:
        artifacts.append(bundle_artifact)
    pv.generated_artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    await db.commit()
    return {"report": report, "artifacts": artifacts}


# ══════════════════════════════════════════════════════════════════════
# 激活动作
# ══════════════════════════════════════════════════════════════════════

def _user_can_view_activation(user: User) -> bool:
    role = (user.role or "").strip()
    return role in (ROLE_ADMIN, ROLE_NETWORK_TEAM)


def _user_can_activate(user: User) -> bool:
    return (user.role or "").strip() == ROLE_ADMIN


async def activate_version(
    db: AsyncSession,
    version_id: int,
    *,
    user: User,
    force: bool = False,
    reason: Optional[str] = None,
) -> ProtocolVersion:
    if not _user_can_activate(user):
        raise HTTPException(status_code=403, detail="仅管理员可激活协议版本")

    res = await db.execute(
        select(ProtocolVersion)
        .where(ProtocolVersion.id == version_id)
        .options(selectinload(ProtocolVersion.protocol))
    )
    pv = res.scalar_one_or_none()
    if pv is None:
        raise HTTPException(status_code=404, detail=f"协议版本 {version_id} 不存在")
    if pv.availability_status == AVAILABILITY_AVAILABLE:
        raise HTTPException(status_code=400, detail="该版本已经是 Available 状态")
    if pv.availability_status == AVAILABILITY_DEPRECATED:
        raise HTTPException(status_code=400, detail="已弃用版本不可激活")
    if pv.availability_status != AVAILABILITY_PENDING_CODE:
        raise HTTPException(
            status_code=400,
            detail=f"仅 PendingCode 状态可激活（当前：{pv.availability_status}）",
        )

    # 读最新报告；若缺失/损坏，先强制重跑体检后再允许激活。
    report: Dict[str, Any] = {}
    if pv.activation_report_json:
        try:
            parsed = json.loads(pv.activation_report_json)
            if isinstance(parsed, dict):
                report = parsed
        except Exception:
            report = {}

    if not report:
        try:
            rebuilt = await refresh_activation_pipeline(db, pv.id)
            report = rebuilt.get("report") or {}
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"激活前无法生成体检报告：{exc}",
            ) from exc

    summary = (report.get("summary") or {}) if isinstance(report, dict) else {}
    if not isinstance(summary, dict):
        raise HTTPException(status_code=400, detail="激活前体检报告格式无效，请先刷新体检")
    red_count = int(summary.get("red") or 0)

    if red_count > 0 and not force:
        raise HTTPException(
            status_code=400,
            detail=f"体检报告存在 {red_count} 项红色风险。请先解决，或使用「强制激活」并填写理由。",
        )
    if force and not (reason or "").strip():
        raise HTTPException(status_code=400, detail="强制激活必须填写理由")

    pv.availability_status = AVAILABILITY_AVAILABLE
    pv.activated_at = datetime.utcnow()
    pv.activated_by = user.username
    pv.forced_activation = bool(force)
    pv.activation_force_reason = (reason or "").strip() or None

    await db.commit()
    await db.refresh(pv)

    # 通知
    proto_name = pv.protocol.name if pv.protocol else ""
    title = f"TSN 协议版本已激活：{proto_name} {pv.version or ''}".strip()
    body_lines = [f"由 {user.username} 激活"]
    if force:
        body_lines.append(f"⚠️ 强制激活（红项 {red_count}）理由：{reason}")
    body = " / ".join(body_lines)
    link = f"/network-config/versions/{pv.id}"
    await notify_users_by_role(
        db, role=ROLE_NETWORK_TEAM,
        kind=NOTIFICATION_KIND_CR_PUBLISHED,
        title=title, body=body, link=link,
    )
    await notify_users_by_role(
        db, role=ROLE_ADMIN,
        kind=NOTIFICATION_KIND_CR_PUBLISHED,
        title=title, body=body, link=link,
    )

    # 按提交者勾选的 notify_teams 发 FYI 通知（飞管/飞控/TSN 团队）
    # 注意：TSN 团队上面已经 notify 过一次；对已经收到通知的角色这里自动去重。
    from ..approval_policy import TSN_NOTIFY_TEAM_ROLES, TSN_NOTIFY_TEAM_LABELS
    notified_roles: set[str] = {ROLE_NETWORK_TEAM, ROLE_ADMIN}
    teams = list(getattr(pv, "notify_teams", None) or [])
    for team_code in teams:
        target_roles = TSN_NOTIFY_TEAM_ROLES.get(team_code) or []
        team_label = TSN_NOTIFY_TEAM_LABELS.get(team_code, team_code)
        for role in target_roles:
            if role in notified_roles:
                continue
            notified_roles.add(role)
            await notify_users_by_role(
                db, role=role,
                kind=NOTIFICATION_KIND_CR_PUBLISHED,
                title=f"TSN 协议已激活变更，请关注：{proto_name} {pv.version or ''}".strip(),
                body=f"激活人：{user.username}；涉及团队：{team_label}",
                link=link,
            )

    await db.commit()
    return pv


# ══════════════════════════════════════════════════════════════════════
# 供路由层消费的读取封装
# ══════════════════════════════════════════════════════════════════════

async def get_activation_report(
    db: AsyncSession, version_id: int, *, ensure: bool = True
) -> Dict[str, Any]:
    """读取 ProtocolVersion 上的报告；若缺失且 ensure=True，则顺便生成一次。"""
    res = await db.execute(
        select(ProtocolVersion).where(ProtocolVersion.id == version_id)
    )
    pv = res.scalar_one_or_none()
    if pv is None:
        raise HTTPException(status_code=404, detail=f"协议版本 {version_id} 不存在")

    report: Optional[Dict[str, Any]] = None
    artifacts: List[Dict[str, Any]] = []
    if pv.activation_report_json:
        try:
            report = json.loads(pv.activation_report_json)
        except Exception:
            report = None
    if pv.generated_artifacts_json:
        try:
            artifacts = json.loads(pv.generated_artifacts_json) or []
        except Exception:
            artifacts = []

    if report is None and ensure:
        result = await refresh_activation_pipeline(db, version_id)
        report = result["report"]
        artifacts = result["artifacts"]

    return {
        "version_id": pv.id,
        "version": pv.version,
        "availability_status": pv.availability_status,
        "activated_at": pv.activated_at.isoformat() + "Z" if pv.activated_at else None,
        "activated_by": pv.activated_by,
        "forced_activation": bool(pv.forced_activation),
        "activation_force_reason": pv.activation_force_reason,
        "report_generated_at": (
            pv.activation_report_generated_at.isoformat() + "Z"
            if pv.activation_report_generated_at else None
        ),
        "report": report,
        "artifacts": artifacts,
    }
