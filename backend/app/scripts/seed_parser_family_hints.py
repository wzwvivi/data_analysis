# -*- coding: utf-8 -*-
"""给 DeviceProtocolSpec.parser_family_hints 填入默认值。

规则：hints 是 *设备级* 属性（不随总线变化），所以同一设备的所有 spec 行
（arinc429 / can / rs485 / ...）共享同一份 hints。

来源：桌面《协议版本管理.xlsx》＋ ParserProfile 的实际 family 列表。
如果以后想自己改，直接走草稿 → 审批 → 发布即可（字段会暴露到 API）。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.database import async_session
from app.models import DeviceProtocolSpec


# device_id 以 anchor（不带 __xxx 后缀）为 key
HINTS_BY_ANCHOR: dict[str, list[str]] = {
    "ata21_21_1": [],
    "ata23_23_1": [],
    "ata23_23_2": [],
    "ata23_23_3": ["atg"],                       # 5GATG

    "ata24_24_1": ["bms270v"],
    "ata24_24_2": ["bpcu_empc"],
    "ata24_24_3": ["bpcu_empc"],

    "ata27_27_1": [],
    "ata27_27_2": [],
    "ata27_27_3": [],
    "ata27_27_4": ["fcc"],                       # 飞控计算机 → fcc_v13

    "ata30_30_1": [],
    "ata30_30_2": [],
    "ata30_30_3": [],

    "ata31_31_1": [],                            # 显控计算机 TSN 接收方：无自身 parser

    "ata32_32_1": ["brake"],
    "ata32_32_2": ["lgcu"],
    "ata32_32_3": ["turn"],

    "ata34_34_1": ["ra"],
    "ata34_34_2": ["adc"],
    "ata34_34_3": ["irs", "fms_irs_fwd"],
    "ata34_34_4": ["rtk"],
    "ata34_34_5": [],                            # CNIU 暂无 parser
    "ata34_34_6": [],
    "ata34_34_7": [],
    "ata34_34_8": ["xpdr"],

    "ata46_46_1": [],

    "ata86_86_1": ["mcu"],
    "ata86_86_2": ["bms800v"],

    "ata90_90_1": [],
    "ata90_90_2": ["fms"],

    "ata92_92_1": ["atg"],
}


def _anchor_of(device_id: str) -> str:
    """把 ata27_27_4__rs485 还原成 ata27_27_4"""
    return device_id.split("__", 1)[0]


async def main():
    async with async_session() as s:
        rows = (
            await s.execute(select(DeviceProtocolSpec).order_by(DeviceProtocolSpec.device_id))
        ).scalars().all()
        updated = 0
        skipped = 0
        for sp in rows:
            anchor = _anchor_of(sp.device_id)
            if anchor not in HINTS_BY_ANCHOR:
                print(f"[SKIP] unknown anchor: {sp.device_id}  ({sp.device_name})")
                skipped += 1
                continue
            desired = list(HINTS_BY_ANCHOR[anchor])
            current = list(sp.parser_family_hints or [])
            if current != desired:
                sp.parser_family_hints = desired
                updated += 1
                print(f"[SET] {sp.device_id:<35}  {current}  →  {desired}")
        await s.commit()
        print(f"\n✓ updated={updated}  skipped={skipped}  total={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
