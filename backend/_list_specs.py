# -*- coding: utf-8 -*-
import asyncio
from sqlalchemy import select
from app.database import async_session as AsyncSessionLocal
from app.models import DeviceProtocolSpec


async def main():
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(DeviceProtocolSpec).order_by(
                    DeviceProtocolSpec.ata_code, DeviceProtocolSpec.device_name
                )
            )
        ).scalars().all()
        print(f"total={len(rows)}")
        for r in rows:
            ata = r.ata_code or "-"
            fam = r.protocol_family
            hints = getattr(r, "parser_family_hints", None)
            print(
                f"{r.id:>3}  {ata:<8} {fam:<9}  {r.device_id:<30}  {r.device_name}  hints={hints}"
            )


if __name__ == "__main__":
    asyncio.run(main())
