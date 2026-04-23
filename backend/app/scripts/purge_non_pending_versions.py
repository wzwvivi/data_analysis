# -*- coding: utf-8 -*-
"""一次性清理脚本：arinc429 家族下，对"有多个版本"的协议，
只保留 availability_status='PendingCode' 的版本，其余（Available / Deprecated）
全部删除。

安全栅栏：
  - 只处理 protocol_family == 'arinc429'
  - 只处理版本数 > 1 的 spec（单版本 spec 一律不动）
  - 如果该 spec 下没有任何 PendingCode 版本，跳过（避免把整条协议删空）
  - 被删前先把 spec.current_version_id / drafts.base_version_id /
    drafts.published_version_id 里指向它的引用清空，防 FK violation

用法：
    docker exec -w /app tsn-backend python -m app.scripts.purge_non_pending_versions
    docker exec -w /app tsn-backend python -m app.scripts.purge_non_pending_versions --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
from typing import List

from sqlalchemy import delete, select, update

from app.database import async_session
from app.models import (
    DeviceProtocolDraft,
    DeviceProtocolSpec,
    DeviceProtocolVersion,
)


async def run(dry_run: bool) -> None:
    total_spec = 0
    skipped_single = 0
    skipped_no_pending = 0
    deleted_versions = 0
    affected_specs = 0

    async with async_session() as db:
        spec_res = await db.execute(
            select(DeviceProtocolSpec)
            .where(DeviceProtocolSpec.protocol_family == "arinc429")
            .order_by(DeviceProtocolSpec.id.asc())
        )
        specs: List[DeviceProtocolSpec] = list(spec_res.scalars().all())
        total_spec = len(specs)

        for spec in specs:
            vres = await db.execute(
                select(DeviceProtocolVersion)
                .where(DeviceProtocolVersion.spec_id == spec.id)
                .order_by(DeviceProtocolVersion.version_seq.asc())
            )
            versions: List[DeviceProtocolVersion] = list(vres.scalars().all())
            if len(versions) <= 1:
                skipped_single += 1
                continue

            pending_ids = {
                v.id for v in versions if v.availability_status == "PendingCode"
            }
            if not pending_ids:
                skipped_no_pending += 1
                print(
                    f"[skip] spec_id={spec.id} device={spec.device_id!r} "
                    f"versions={len(versions)} 无 PendingCode，跳过"
                )
                continue

            to_delete = [v for v in versions if v.id not in pending_ids]
            if not to_delete:
                continue

            names = ", ".join(f"{v.version_name}(id={v.id})" for v in to_delete)
            kept = ", ".join(
                f"{v.version_name}(id={v.id})" for v in versions if v.id in pending_ids
            )
            print(
                f"[{'DRY' if dry_run else ' DO'}] spec_id={spec.id} "
                f"device={spec.device_id!r} 保留 [{kept}] 删除 [{names}]"
            )

            if dry_run:
                deleted_versions += len(to_delete)
                affected_specs += 1
                continue

            del_ids = [v.id for v in to_delete]

            # 1) 清 spec.current_version_id 指向（若指向被删者，改指向任一 PendingCode）
            if spec.current_version_id in del_ids:
                new_cur = next(iter(pending_ids))
                spec.current_version_id = new_cur

            # 2) 清 drafts.base_version_id / published_version_id
            await db.execute(
                update(DeviceProtocolDraft)
                .where(DeviceProtocolDraft.base_version_id.in_(del_ids))
                .values(base_version_id=None)
            )
            await db.execute(
                update(DeviceProtocolDraft)
                .where(DeviceProtocolDraft.published_version_id.in_(del_ids))
                .values(published_version_id=None)
            )

            # 3) 删版本
            await db.execute(
                delete(DeviceProtocolVersion).where(
                    DeviceProtocolVersion.id.in_(del_ids)
                )
            )
            deleted_versions += len(del_ids)
            affected_specs += 1

        if not dry_run:
            await db.commit()

    print("\n========== Summary ==========")
    print(f"total arinc429 specs scanned : {total_spec}")
    print(f"  skipped (single version)   : {skipped_single}")
    print(f"  skipped (no PendingCode)   : {skipped_no_pending}")
    print(f"  specs affected             : {affected_specs}")
    print(f"  versions deleted           : {deleted_versions}")
    if dry_run:
        print("\n(dry-run: 未提交任何变更)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="只打印待删清单，不真删")
    args = p.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
