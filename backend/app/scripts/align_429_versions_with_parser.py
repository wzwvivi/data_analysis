# -*- coding: utf-8 -*-
"""一次性脚本：把 429 DeviceProtocolVersion 的版本号对齐到平台 ParserProfile.version。

按用户决策：
- 规则：对每个有 parser_family_hints 的 429 spec，找到对应 ParserProfile.version，
  把"最新版"的 version_name 改成它，并同步 spec_json.protocol_meta.version 和 version_info.version。
- 若 version 不以 V/v 开头（如 "20260113"）自动补 V 前缀。
- 特殊处理：32-3-转弯 有两条老垃圾版本（V9.0/V10.0），删除 V9.0，把 V10.0 重命名为 V2.0（seq 重置为 1）。
- 无 hints 的空壳设备（含 27-4-飞控）不动。

跑法：
    docker exec -w /app tsn-backend python -m app.scripts.align_429_versions_with_parser
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select, delete

from app.database import async_session
from app.models import DeviceProtocolSpec, DeviceProtocolVersion, ParserProfile


def _normalize_version(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    v = raw.strip()
    if not v:
        return None
    if v[0] in ("V", "v"):
        return "V" + v[1:]
    return "V" + v


async def _best_version_for_family(db, family: str) -> Optional[str]:
    """同 family 多条 ParserProfile 时，挑 version 非空的那条。"""
    res = await db.execute(
        select(ParserProfile).where(ParserProfile.protocol_family == family)
    )
    profiles = list(res.scalars().all())
    candidates = [_normalize_version(p.version) for p in profiles]
    for v in candidates:
        if v:
            return v
    return None


async def _purge_turn_legacy(db, spec: DeviceProtocolSpec) -> List[str]:
    """32-3-转弯：删 V9.0，把 V10.0 改 V2.0 并 seq=1。返回操作日志。"""
    logs: List[str] = []
    vres = await db.execute(
        select(DeviceProtocolVersion)
        .where(DeviceProtocolVersion.spec_id == spec.id)
        .order_by(DeviceProtocolVersion.version_seq.asc())
    )
    versions = list(vres.scalars().all())
    v9 = next((v for v in versions if v.version_name == "V9.0"), None)
    latest = versions[-1] if versions else None

    if v9 is not None:
        # 如果 current_version_id 恰好指向要删的 V9，先搬走
        if spec.current_version_id == v9.id and latest and latest.id != v9.id:
            spec.current_version_id = latest.id
        await db.execute(
            delete(DeviceProtocolVersion).where(DeviceProtocolVersion.id == v9.id)
        )
        logs.append(f"删除老版 V9.0 (id={v9.id})")

    # 重新拉 latest，改名
    vres2 = await db.execute(
        select(DeviceProtocolVersion)
        .where(DeviceProtocolVersion.spec_id == spec.id)
        .order_by(DeviceProtocolVersion.version_seq.desc())
    )
    latest = vres2.scalars().first()
    if latest and latest.version_name != "V2.0":
        _rename_version_inplace(latest, "V2.0", seq=1)
        logs.append(f"重命名 {latest.id} → V2.0, seq=1")
    return logs


def _rename_version_inplace(
    v: DeviceProtocolVersion, new_name: str, *, seq: Optional[int] = None
) -> None:
    """in-place 改 version_name + spec_json 里的版本字段 + seq。"""
    v.version_name = new_name
    if seq is not None:
        v.version_seq = seq
    spec_json = dict(v.spec_json or {})
    meta = dict(spec_json.get("protocol_meta") or {})
    meta["version"] = new_name
    spec_json["protocol_meta"] = meta
    vi = dict(spec_json.get("version_info") or {})
    vi["version"] = new_name
    spec_json["version_info"] = vi
    v.spec_json = spec_json  # 触发 JSON 脏标记


async def main() -> None:
    async with async_session() as db:
        res = await db.execute(
            select(DeviceProtocolSpec)
            .where(DeviceProtocolSpec.protocol_family == "arinc429")
            .order_by(DeviceProtocolSpec.device_id)
        )
        specs = list(res.scalars().all())
        print(f"共 {len(specs)} 条 429 spec，开始对齐版本号…\n")

        logs: List[str] = []

        for s in specs:
            hints = s.parser_family_hints or []
            if not hints:
                logs.append(f"  SKIP [{s.device_id}] {s.device_name}  (无 hints)")
                continue
            family = hints[0]
            target = await _best_version_for_family(db, family)
            if not target:
                logs.append(
                    f"  SKIP [{s.device_id}] {s.device_name}  "
                    f"(parser family={family} 的 version 为空)"
                )
                continue

            # 特殊：32-3 转弯处理垃圾历史版
            if s.device_id == "ata32_32_3":
                sub_logs = await _purge_turn_legacy(db, s)
                for line in sub_logs:
                    logs.append(f"  TURN [{s.device_id}] {line}")
                continue

            # 其它：找最新版直接改名
            vres = await db.execute(
                select(DeviceProtocolVersion)
                .where(DeviceProtocolVersion.spec_id == s.id)
                .order_by(DeviceProtocolVersion.version_seq.desc())
            )
            latest = vres.scalars().first()
            if not latest:
                logs.append(
                    f"  SKIP [{s.device_id}] {s.device_name}  (无版本；不会被 align 创建)"
                )
                continue
            if latest.version_name == target:
                logs.append(
                    f"  OK   [{s.device_id}] {s.device_name}  已是 {target}，跳过"
                )
                continue

            # 检查 target 是否已存在于该 spec 其它版本（理论上不会，这里兜底）
            dup = await db.execute(
                select(DeviceProtocolVersion.id)
                .where(DeviceProtocolVersion.spec_id == s.id)
                .where(DeviceProtocolVersion.version_name == target)
            )
            if dup.first() is not None:
                logs.append(
                    f"  SKIP [{s.device_id}] {s.device_name}  目标 {target} 已存在，避免冲突"
                )
                continue

            old_name = latest.version_name
            _rename_version_inplace(latest, target)
            logs.append(
                f"  REN  [{s.device_id}] {s.device_name}  {old_name} → {target}"
            )

        await db.commit()

        print("=== 对齐结果 ===")
        for line in logs:
            print(line)
        print("\n✅ done.")


if __name__ == "__main__":
    asyncio.run(main())
