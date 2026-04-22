# -*- coding: utf-8 -*-
"""一次性脚本：把桌面「协议平台」的设备树同步过来

读取桌面 ``c:\\Users\\wangz\\Desktop\\协议\\generator\\data\\arinc429.db`` 中的
``devices`` 表，作为设备树**骨架**导入到 tsn-log-analyzer：

1. 每个 ATA 系统（``is_device=0, parent_id IS NULL``）→ UPSERT 到 ``ata_systems``
   元表（``code = device_id`` 如 ``ata32``；``display_name = name`` 如
   ``ATA32-起落架系统``；``sort_order`` 从 code 里挖出数字 ``32``）。
2. 每个真实设备（``is_device=1``）→ UPSERT 到 ``device_protocol_specs``
   （按 ``(protocol_family, device_id)`` 查重；已存在只**补元数据**，不碰版本）。

策略（与用户确认）：
    - 跳过桌面上自建的 ``sys_1774252828`` / ``ata-100`` 这套测试系统。
    - 没有协议族信息时按名字推断：含 CAN / BMS / 电驱 → can；含 ``-429`` / ``ARINC429`` → arinc429；
      其余默认 ``arinc429``。
    - 纯骨架导入：**不写 versions / labels**。已经有版本的设备（例如手动
      M1 导入过 labels 的 4 台）不会受影响，只会补齐 ATA 元表和名字。

使用：

::

    # 在宿主机（Windows）跑，默认读本地 desktop DB + 写本地 backend-runtime DB
    cd tsn-log-analyzer\\backend
    python -m app.scripts.seed_device_tree_from_protocol_platform --dry-run

    # 确认无误后去掉 --dry-run
    python -m app.scripts.seed_device_tree_from_protocol_platform

    # 或者在 Docker 里跑（需先把 desktop DB 挂进容器）
    docker compose exec tsn-backend \\
        python -m app.scripts.seed_device_tree_from_protocol_platform \\
        --desktop-db /desktop/arinc429.db
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from ..database import async_session, init_db
from ..models.device_protocol import (
    DEVICE_SPEC_ACTIVE,
    PROTOCOL_FAMILY_ARINC429,
    PROTOCOL_FAMILY_CAN,
    PROTOCOL_FAMILY_RS422,
    AtaSystem,
    DeviceProtocolSpec,
)


DEFAULT_DESKTOP_DB = Path(r"c:\Users\wangz\Desktop\协议\generator\data\arinc429.db")

# 桌面上这几套是用户自建的"自定-429"测试节点，骨架导入时跳掉
SKIP_SYSTEM_IDS = {"sys_1774252828"}

_ATA_CODE_RE = re.compile(r"^ata(\d+)$", re.IGNORECASE)
_ATA_NAME_RE = re.compile(r"^ATA\s*(\d+)", re.IGNORECASE)


def _infer_family(device_name: str) -> str:
    """按桌面设备命名习惯推断协议族。"""
    name = (device_name or "").lower()
    if any(kw in name for kw in ("can", "bms", "电驱", "电池")):
        return PROTOCOL_FAMILY_CAN
    if "rs422" in name or "422" in name.replace("-429", ""):
        # 桌面命名里 422 并不常见，保守起见走这条
        return PROTOCOL_FAMILY_RS422
    # ARINC429 / -429 / 其它默认一律落到 arinc429
    return PROTOCOL_FAMILY_ARINC429


def _ata_sort_order(code: str) -> int:
    m = _ATA_CODE_RE.match((code or "").strip())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 99_999
    return 99_999


def _load_desktop_devices(
    desktop_db_path: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """返回 (ata_systems, devices) 两份列表，都按 device_id 去重。"""
    if not desktop_db_path.exists():
        raise FileNotFoundError(f"找不到桌面 DB：{desktop_db_path}")
    conn = sqlite3.connect(str(desktop_db_path))
    try:
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        cur = conn.cursor()
        cur.execute(
            "SELECT id, device_id, name, parent_id, is_device, device_version, "
            "current_version_name FROM devices ORDER BY id"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # 用数据库主键 id 做父子索引
    id_to_row = {r[0]: r for r in rows}

    ata_systems: List[Dict[str, Any]] = []
    devices: List[Dict[str, Any]] = []

    for (rid, device_id, name, parent_id, is_device, device_version, cvn) in rows:
        if device_id in SKIP_SYSTEM_IDS:
            continue
        # 判断是否属于被跳过系统的子设备
        if parent_id and id_to_row.get(parent_id, [None, None])[1] in SKIP_SYSTEM_IDS:
            continue

        # 规范化：如果顶层（parent_id IS NULL）且名字形如 "ATA52-xxx"，强制当 ATA
        # 系统处理（桌面上偶尔会把 ATA 节点错标成 is_device=1）。
        is_top_ata_by_name = parent_id is None and bool(_ATA_NAME_RE.match(name or ""))
        effective_is_device = bool(is_device) and not is_top_ata_by_name

        entry = {
            "desktop_pk": rid,
            "device_id": device_id,
            "name": name,
            "parent_id": parent_id,
            "is_device": effective_is_device,
            "device_version": device_version or "V1.0",
            "current_version_name": cvn or "",
        }
        if effective_is_device:
            # 找到它的 ATA 系统祖先（最顶层 parent_id=None 的节点）
            cur_id = parent_id
            ata_code = None
            parent_path: List[str] = []
            while cur_id is not None and cur_id in id_to_row:
                p = id_to_row[cur_id]
                parent_path.insert(0, p[2])  # name
                if p[3] is None:  # 顶层
                    ata_code = p[1]  # device_id of top-level = ata23
                    break
                cur_id = p[3]
            entry["ata_code"] = ata_code
            entry["parent_path"] = parent_path
            devices.append(entry)
        else:
            # 只收顶层 ATA 节点（parent_id=None 且 is_device=0）
            if parent_id is None:
                ata_systems.append(entry)

    return ata_systems, devices


async def _upsert_ata_systems(
    db, ata_rows: List[Dict[str, Any]], dry_run: bool
) -> Dict[str, int]:
    """UPSERT ATA 元表。返回 {'created': n, 'updated': n, 'unchanged': n}."""
    res = await db.execute(select(AtaSystem))
    existing: Dict[str, AtaSystem] = {row.code: row for row in res.scalars().all()}

    stats = {"created": 0, "updated": 0, "unchanged": 0}
    for row in ata_rows:
        code = row["device_id"]
        display = row["name"]
        sort_order = _ata_sort_order(code)
        prev = existing.get(code)
        if prev:
            changed = False
            if prev.display_name != display:
                prev.display_name = display
                changed = True
            if prev.sort_order != sort_order:
                prev.sort_order = sort_order
                changed = True
            if changed:
                prev.updated_at = datetime.utcnow()
                stats["updated"] += 1
                if not dry_run:
                    db.add(prev)
            else:
                stats["unchanged"] += 1
            continue

        stats["created"] += 1
        if not dry_run:
            db.add(
                AtaSystem(
                    code=code,
                    display_name=display,
                    sort_order=sort_order,
                    description=None,
                )
            )
    if not dry_run:
        await db.flush()
    return stats


async def _upsert_devices(
    db, devices: List[Dict[str, Any]], *, user: str, dry_run: bool
) -> Dict[str, int]:
    """UPSERT DeviceProtocolSpec 骨架。已存在 spec 补齐 name/ata_code/parent_path."""
    stats = {
        "created": 0,
        "updated_meta": 0,
        "unchanged": 0,
        "by_family": {"arinc429": 0, "can": 0, "rs422": 0},
    }

    for row in devices:
        family = _infer_family(row["name"])
        stats["by_family"][family] += 1

        res = await db.execute(
            select(DeviceProtocolSpec).where(
                DeviceProtocolSpec.protocol_family == family,
                DeviceProtocolSpec.device_id == row["device_id"],
            )
        )
        prev: Optional[DeviceProtocolSpec] = res.scalar_one_or_none()
        if prev:
            changed = False
            if prev.device_name != row["name"]:
                prev.device_name = row["name"]
                changed = True
            if prev.ata_code != row["ata_code"]:
                prev.ata_code = row["ata_code"]
                changed = True
            want_parent = row["parent_path"] or None
            if (prev.parent_path or None) != want_parent:
                prev.parent_path = want_parent
                changed = True
            if changed:
                prev.updated_at = datetime.utcnow()
                stats["updated_meta"] += 1
                if not dry_run:
                    db.add(prev)
            else:
                stats["unchanged"] += 1
            continue

        stats["created"] += 1
        if not dry_run:
            db.add(
                DeviceProtocolSpec(
                    protocol_family=family,
                    ata_code=row["ata_code"],
                    device_id=row["device_id"],
                    device_name=row["name"],
                    parent_path=row["parent_path"] or None,
                    description=None,
                    status=DEVICE_SPEC_ACTIVE,
                    created_by=user,
                )
            )
    if not dry_run:
        await db.flush()
    return stats


async def main_async(args: argparse.Namespace) -> int:
    desktop_db = Path(args.desktop_db).expanduser()
    try:
        ata_rows, device_rows = _load_desktop_devices(desktop_db)
    except FileNotFoundError as e:
        print(f"[ERR] {e}", file=sys.stderr)
        return 2

    print(f"[INFO] 桌面 DB：{desktop_db}")
    print(f"[INFO] 读取 ATA 系统 {len(ata_rows)} 条，设备 {len(device_rows)} 条（已过滤 {sorted(SKIP_SYSTEM_IDS)}）")
    if args.limit_devices:
        device_rows = device_rows[: args.limit_devices]
        print(f"[INFO] --limit-devices 裁剪到 {len(device_rows)} 条")

    # 确保 ata_systems 表存在（首次跑时）
    await init_db()

    async with async_session() as db:
        ata_stats = await _upsert_ata_systems(db, ata_rows, dry_run=args.dry_run)
        dev_stats = await _upsert_devices(
            db, device_rows, user=args.user, dry_run=args.dry_run
        )
        if not args.dry_run:
            await db.commit()
        else:
            await db.rollback()

    # ── 结果打印 ──
    print("\n=== ATA 系统元表 ===")
    for k, v in ata_stats.items():
        print(f"  {k:<12}: {v}")

    print("\n=== 设备骨架 ===")
    print(f"  created     : {dev_stats['created']}")
    print(f"  updated_meta: {dev_stats['updated_meta']}")
    print(f"  unchanged   : {dev_stats['unchanged']}")
    print(f"  by_family   : {dev_stats['by_family']}")

    if args.dry_run:
        print("\n[NOTE] --dry-run 已回滚；重跑时去掉 --dry-run 真正写入。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="从桌面协议平台 SQLite 读取设备树，同步到 tsn-log-analyzer"
    )
    p.add_argument(
        "--desktop-db",
        default=str(DEFAULT_DESKTOP_DB),
        help=f"桌面 arinc429.db 路径（默认 {DEFAULT_DESKTOP_DB}）",
    )
    p.add_argument("--user", default="migration", help="新建 spec 的 created_by（默认 migration）")
    p.add_argument("--dry-run", action="store_true", help="只打印不写入")
    p.add_argument(
        "--limit-devices",
        type=int,
        default=0,
        help="只处理前 N 条设备（调试用，0 = 不限制）",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
