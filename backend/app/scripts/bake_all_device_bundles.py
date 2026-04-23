# -*- coding: utf-8 -*-
"""一次性脚本：为每个 DeviceProtocolVersion 生成 services/generated_device/v{id}/bundle.json

用途：
- P1/P2 schema 补齐 + spec_json backfill 之后，需要把历史版本也烘焙成 device bundle
- 今后每次 publish 会自动生成，这个脚本只是补齐历史数据

    docker exec -w /app tsn-backend python -m app.scripts.bake_all_device_bundles
    docker exec -w /app tsn-backend python -m app.scripts.bake_all_device_bundles --only arinc429
    docker exec -w /app tsn-backend python -m app.scripts.bake_all_device_bundles --skip-existing
"""
from __future__ import annotations

import argparse
import asyncio
from typing import List

from sqlalchemy import select

from app.database import async_session
from app.models import DeviceProtocolSpec, DeviceProtocolVersion
from app.services.device_bundle import (
    device_bundle_exists,
    generate_device_bundle,
)


async def run(
    *,
    only_family: str = "",
    skip_existing: bool = False,
) -> None:
    async with async_session() as db:
        qs = select(DeviceProtocolSpec)
        if only_family:
            qs = qs.where(DeviceProtocolSpec.protocol_family == only_family)
        sres = await db.execute(qs)
        specs = list(sres.scalars().all())

        vres = await db.execute(
            select(DeviceProtocolVersion).where(
                DeviceProtocolVersion.spec_id.in_([s.id for s in specs])
            )
        )
        versions = list(vres.scalars().all())
        print(
            f"[bake] 发现 {len(specs)} 个 spec，{len(versions)} 个 version "
            f"(family={only_family or 'all'})"
        )

        ok: List[int] = []
        skipped: List[int] = []
        failed: List[str] = []
        for v in versions:
            if skip_existing and device_bundle_exists(v.id):
                skipped.append(v.id)
                continue
            try:
                meta = await generate_device_bundle(db, v.id)
                stats = meta.get("stats") or {}
                print(
                    f"  ✅ v{v.id:>4d} {stats.get('device_id','?'):>10s} "
                    f"{v.version_name:>8s} labels={stats.get('labels',0):>3d} "
                    f"bnr={stats.get('bnr_fields',0):>3d} "
                    f"bcd={stats.get('bcd_pattern_count',0):>2d} "
                    f"po={stats.get('port_override_count',0):>2d} "
                    f"ssm={stats.get('ssm_semantics_count',0):>2d} "
                    f"bytes={meta.get('bytes_written',0)}"
                )
                ok.append(v.id)
            except Exception as exc:  # noqa: BLE001
                msg = f"  ❌ v{v.id} ({v.version_name}): {exc}"
                print(msg)
                failed.append(msg)

    print("\n=== 汇总 ===")
    print(f"  generated: {len(ok)}")
    print(f"  skipped  : {len(skipped)}")
    print(f"  failed   : {len(failed)}")
    if failed:
        print("\n失败明细：")
        for line in failed:
            print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="批量烘焙 DeviceProtocolVersion → bundle.json")
    ap.add_argument("--only", default="", help="只处理指定 family，例如 arinc429")
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="跳过已经生成过 bundle 的 version",
    )
    args = ap.parse_args()
    asyncio.run(run(only_family=args.only, skip_existing=args.skip_existing))


if __name__ == "__main__":
    main()
