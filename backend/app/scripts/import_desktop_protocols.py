# -*- coding: utf-8 -*-
"""一次性导入桌面协议平台历史数据

扫描 ``<root>/git_repos/protocol-*/devices/*/current/protocol.json``，
把每个 ``protocol.json`` 作为「首个已发布版本」直接登记到当前平台：
    - 新建 ``DeviceProtocolSpec``（ata_code / device_id / device_name / family）
    - 新建 ``DeviceProtocolVersion``（version_seq=1, availability=PendingCode,
      git_export_status=skipped，绕过审批流）
    - 直接跳过审批与 git 导出（M1 仅需要数据存在，以便平台能看到历史设备）

使用：
    # 宿主机 Python
    cd backend
    python -m app.scripts.import_desktop_protocols \\
        --root "C:/Users/wangz/Desktop/协议/generator/git_repos" \\
        --user "migration" [--dry-run]

    # docker exec
    docker compose exec tsn-backend python -m app.scripts.import_desktop_protocols \\
        --root "/data/desktop-protocols"

默认只导入 ARINC429（desktop generator 目前就是 429）；CAN / RS422 待后续迁移。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from ..database import async_session, init_db
from ..models.device_protocol import (
    DEVICE_SPEC_ACTIVE,
    GIT_EXPORT_SKIPPED,
    PROTOCOL_FAMILY_ARINC429,
    DeviceProtocolSpec,
    DeviceProtocolVersion,
)
from ..services.protocol_family import get_family_handler

# 与设备版本表 availability_status 的取值保持一致（见 DeviceProtocolVersion）
_AVAILABILITY_PENDING_CODE = "PendingCode"


# ───────────── 工具函数 ─────────────


def iter_protocol_files(root: Path) -> List[Tuple[str, Path]]:
    """返回 [(repo_name, protocol_json_path), ...]"""
    out: List[Tuple[str, Path]] = []
    if not root.exists():
        return out
    for repo_dir in sorted(root.iterdir()):
        if not repo_dir.is_dir() or not repo_dir.name.startswith("protocol-"):
            continue
        devices_dir = repo_dir / "devices"
        if not devices_dir.exists():
            continue
        for dev_dir in sorted(devices_dir.iterdir()):
            if not dev_dir.is_dir():
                continue
            pfile = dev_dir / "current" / "protocol.json"
            if pfile.exists():
                out.append((repo_dir.name, pfile))
    return out


def _infer_ata_code(repo_name: str, device_meta_ref: Dict[str, Any]) -> Optional[str]:
    # 优先取 protocol.json 里的 device_meta_ref.ata_code，落到小写；保留 repo 后缀作兜底
    v = (device_meta_ref or {}).get("ata_code")
    if v:
        s = str(v).strip().lower()
        return s or None
    # 从 repo 名 protocol-ata32 / protocol-default 反推
    if repo_name.startswith("protocol-"):
        tail = repo_name[len("protocol-") :].strip().lower()
        return tail or None
    return None


def _infer_device_name(data: Dict[str, Any], fallback: str) -> str:
    meta = data.get("protocol_meta") or {}
    name = str(meta.get("name") or "").strip()
    if name:
        return name
    return fallback


def _infer_version(data: Dict[str, Any]) -> str:
    version_info = data.get("version_info") or {}
    meta = data.get("protocol_meta") or {}
    return str(version_info.get("version") or meta.get("version") or "V1.0").strip() or "V1.0"


# ───────────── 导入主流程 ─────────────


async def import_one(
    db, repo_name: str, path: Path, user: str, dry_run: bool
) -> Dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    dev_meta = raw.get("device_meta_ref") or {}
    device_id = str(dev_meta.get("device_id") or path.parent.parent.name).strip()
    ata_code = _infer_ata_code(repo_name, dev_meta)
    device_name = _infer_device_name(raw, device_id)
    version_name = _infer_version(raw)
    family = PROTOCOL_FAMILY_ARINC429  # 桌面 generator 仅支持 429

    # 归一化 spec_json（对齐 FamilyHandler.normalize_spec）
    handler = get_family_handler(family)
    spec_json = handler.normalize_spec(raw)
    # 强制写入 protocol_meta.name / version / description
    spec_json.setdefault("protocol_meta", {})
    spec_json["protocol_meta"].setdefault("name", device_name)
    spec_json["protocol_meta"]["version"] = version_name
    spec_json["protocol_meta"].setdefault("description", "")

    # 查重：相同 family+device_id 若已存在，跳过
    res = await db.execute(
        select(DeviceProtocolSpec)
        .where(DeviceProtocolSpec.protocol_family == family)
        .where(DeviceProtocolSpec.device_id == device_id)
    )
    existing = res.scalar_one_or_none()
    if existing:
        return {
            "status": "skipped",
            "reason": f"spec {family}:{device_id} 已存在",
            "device_id": device_id,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "device_id": device_id,
            "device_name": device_name,
            "ata_code": ata_code,
            "version_name": version_name,
            "label_count": len(spec_json.get("labels", [])),
        }

    spec = DeviceProtocolSpec(
        protocol_family=family,
        ata_code=ata_code,
        device_id=device_id,
        device_name=device_name,
        description=(raw.get("protocol_meta") or {}).get("description") or "",
        status=DEVICE_SPEC_ACTIVE,
        created_by=user,
    )
    db.add(spec)
    await db.flush()

    version = DeviceProtocolVersion(
        spec_id=spec.id,
        version_name=version_name,
        version_seq=1,
        description=f"[迁移导入] 来自桌面平台 {repo_name}/{device_id} @ {version_name}",
        spec_json=spec_json,
        availability_status=_AVAILABILITY_PENDING_CODE,
        git_export_status=GIT_EXPORT_SKIPPED,
        git_commit_hash=None,
        created_by=user,
        created_at=datetime.utcnow(),
    )
    db.add(version)
    await db.commit()

    return {
        "status": "imported",
        "spec_id": spec.id,
        "version_id": version.id,
        "device_id": device_id,
        "device_name": device_name,
        "ata_code": ata_code,
        "version_name": version_name,
        "label_count": len(spec_json.get("labels", [])),
    }


async def main_async(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"[ERR] 根目录不存在: {root}")
        return 2
    items = iter_protocol_files(root)
    if not items:
        print(f"[WARN] {root} 下未发现任何 protocol-*/devices/*/current/protocol.json")
        return 0

    print(f"[INFO] 发现 {len(items)} 个设备 protocol.json")
    # 初始化 DB schema（如首次运行）
    await init_db()

    summary = {"imported": 0, "skipped": 0, "dry_run": 0, "failed": 0}
    async with async_session() as db:
        for repo_name, path in items:
            try:
                r = await import_one(db, repo_name, path, args.user, args.dry_run)
                summary[r.get("status", "failed")] = summary.get(r.get("status", "failed"), 0) + 1
                print(
                    f"[{r['status'].upper():<8}] {repo_name} / {path.parent.parent.name}"
                    + (f"  -> {r.get('version_name')} ({r.get('label_count')} labels)" if r.get("version_name") else "")
                    + (f"  reason={r.get('reason')}" if r.get("reason") else "")
                )
            except Exception as e:  # noqa: BLE001
                summary["failed"] += 1
                print(f"[FAIL]    {repo_name} / {path}: {e}")
                # 发生异常后保留事务独立性
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass

    print("\n=== 导入完成 ===")
    for k, v in summary.items():
        print(f"  {k:<8}: {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="从桌面协议平台 git_repos 迁移到 tsn-log-analyzer")
    p.add_argument("--root", required=True, help="指向桌面 git_repos 目录")
    p.add_argument("--user", default="migration", help="记为该用户创建（默认 migration）")
    p.add_argument("--dry-run", action="store_true", help="仅扫描不写库")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
