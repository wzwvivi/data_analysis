# -*- coding: utf-8 -*-
import asyncio
from sqlalchemy import select
from app.database import async_session
from app.models import ParserProfile


async def main():
    async with async_session() as s:
        rows = (
            await s.execute(select(ParserProfile).order_by(ParserProfile.protocol_family))
        ).scalars().all()
        print(f"total={len(rows)}")
        for r in rows:
            fam = getattr(r, "protocol_family", None) or "-"
            name = r.name
            dm = getattr(r, "device_model", None)
            key = r.parser_key
            print(f"{fam:<20} {key:<28} name='{name}'  device_model='{dm}'")


if __name__ == "__main__":
    asyncio.run(main())
