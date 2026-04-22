# -*- coding: utf-8 -*-
"""一次性草稿：把 device_protocol_specs 和 parser_profiles 做自动匹配，输出 review 表。

不写库，只打印。人工校对完再跑真正的落库脚本。
"""
import asyncio
import re

from sqlalchemy import select

from app.database import async_session
from app.models.device_protocol import DeviceProtocolSpec
from app.models.protocol import ParserProfile


# parser_family -> 用于 device_name 模糊匹配的正则表
# 语料取自 parser_profiles.device_model / name
FAMILY_KEYWORDS = {
    "adc":         [r"adc", r"大气数据", r"adru"],
    "atg":         [r"\batg\b", r"5g\s*atg", r"\bcpe\b"],
    "bms270v":     [r"270v.*28v|28v.*270v|270v\s*[&_]\s*28v"],
    "bms800v":     [r"800v.*bms|bms.*800v|动力电池.*800v|800v.*动力"],
    "bpcu_empc":   [r"bpcu", r"empc", r"配电盘", r"配电单元", r"配电系统", r"\bpdu\b"],
    "brake":       [r"刹车", r"bcmu", r"abcu", r"brake"],
    "fcc":         [r"飞控计算机", r"\bfcc\b"],
    "fms":         [r"显控计算机", r"飞管(?!给)", r"飞管-飞控"],
    "fms_irs_fwd": [r"飞管给惯导", r"fms.*irs"],
    "irs":         [r"\birs\b", r"惯性基准", r"惯导"],
    "lgcu":        [r"lgcu", r"收放控制"],
    "mcu":         [r"\bmcu\b", r"电驱", r"电推"],
    "ra":          [r"无线电高度表", r"\bra\b"],
    "rtk":         [r"\brtk\b"],
    "turn":        [r"转弯", r"前轮"],
    "xpdr":        [r"xpdr", r"应答机", r"s模式"],
}


def match_families(name: str):
    s = (name or "").lower()
    hits = []
    for fam, pats in FAMILY_KEYWORDS.items():
        for pat in pats:
            # re.ASCII 让 \b 只认 ASCII 词边界，避免中文把英文 token 粘在一起
            if re.search(pat, s, flags=re.ASCII):
                hits.append(fam)
                break
    return hits


async def main():
    async with async_session() as db:
        profiles = (await db.execute(select(ParserProfile))).scalars().all()
        fam2profiles = {}
        for p in profiles:
            fam2profiles.setdefault(p.protocol_family, []).append(p)

        specs = (
            await db.execute(
                select(DeviceProtocolSpec).order_by(
                    DeviceProtocolSpec.ata_code, DeviceProtocolSpec.id
                )
            )
        ).scalars().all()

        print(
            f"{'id':>3}  {'ata':<8} {'bus':<9}  {'device_name':<36}  matched parser families"
        )
        print("-" * 110)
        matched = 0
        for s in specs:
            hits = match_families(s.device_name)
            if hits:
                matched += 1
                parts = []
                for fam in hits:
                    prof = next(
                        (p for p in fam2profiles.get(fam, []) if p.is_active),
                        None,
                    )
                    if prof:
                        parts.append(f"{fam}({prof.parser_key})")
                    else:
                        parts.append(fam)
                tag = "  "
                rhs = ", ".join(parts)
            else:
                tag = "??"
                rhs = "(no match)"
            print(
                f"{s.id:>3}  {s.ata_code or '':<8} {s.protocol_family:<9}  "
                f"{s.device_name:<36}  {tag} {rhs}"
            )
        print("-" * 110)
        print(f"matched: {matched}/{len(specs)}")


asyncio.run(main())
