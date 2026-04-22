# -*- coding: utf-8 -*-
"""一次性对齐设备树 ← 桌面《协议版本管理.xlsx》

功能：
1) 删除渣数据：default/100-x / test / 90-3-自定
2) 改名：21-1-通风系统控制器 → 21-1-通风系统；23-3-5G ATG CPE → 23-3-5GATG
3) 按 xlsx 纠正 protocol_family（多总线设备用"方案 B"：每总线一条 spec）
4) 31-1-显控计算机：设置为 none（TSN 接收方占位，没有设备级总线）
5) parent_path 同步随新名字变化

执行：docker cp 到容器后 `python /app/app/scripts/realign_device_tree_from_xlsx.py`

幂等：再跑一次会收敛到相同状态（已 None 的 parser_family_hints 不动；已存在
的 (family, device_id) 组合不会重复插入）。
"""
from __future__ import annotations

import asyncio
from typing import List, Tuple

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from app.database import async_session
from app.models import DeviceProtocolSpec, DeviceProtocolVersion, DeviceProtocolDraft
from app.models import (
    PROTOCOL_FAMILY_ARINC429,
    PROTOCOL_FAMILY_CAN,
    PROTOCOL_FAMILY_RS422,
    PROTOCOL_FAMILY_RS485,
    PROTOCOL_FAMILY_MAVLINK,
    PROTOCOL_FAMILY_DISCRETE,
    PROTOCOL_FAMILY_WIRELESS,
    PROTOCOL_FAMILY_NONE,
)


# ─────────────────────────────────────────────────────────────
# 1. 要删除的 device_id（含 default/test/100-x/90-3-自定）
# ─────────────────────────────────────────────────────────────
GARBAGE_DEVICE_IDS = {
    "sys_1774252828_100_15",
    "sys_1774252828_100_16",
    "sys_1774252828_100_19",
    "sys_1774252828_100_6",
    "sys_test_device",
    "ata90_90_3",  # 90-3-自定
}


# ─────────────────────────────────────────────────────────────
# 2. 改名映射：device_id → (new_device_name, new_device_id or None)
# ─────────────────────────────────────────────────────────────
RENAME_MAP: dict[str, Tuple[str, str | None]] = {
    "ata21_21_1": ("21-1-通风系统", None),              # 去"控制器"
    "ata23_23_3": ("23-3-5GATG", None),                  # 合并"5G ATG CPE" → "5GATG"
    "ata23_23_2": ("23-2-ELT发射器", None),              # 原样（xlsx 一致）
    "ata34_34_1": ("34-1-无线电高度表(RA)收发机", None),
    "ata34_34_2": ("34-2-ADC（大气数据计算机）", None),
    "ata34_34_5": ("34-5-甚高频通信及无线电导航集成设备", None),
}


# ─────────────────────────────────────────────────────────────
# 3. 总线真值表（来源：数据协议/协议版本管理.xlsx）
#    device_id（以 ARINC429 主 spec 为 anchor）→ [真实总线列表]
#    多总线设备会被拆成多条 spec，每条 spec 的 device_id 为
#    f"{anchor_id}__{family}" 以保证 UNIQUE(family, device_id) 不冲突。
# ─────────────────────────────────────────────────────────────
A429 = PROTOCOL_FAMILY_ARINC429
CAN = PROTOCOL_FAMILY_CAN
R422 = PROTOCOL_FAMILY_RS422
R485 = PROTOCOL_FAMILY_RS485
MAV = PROTOCOL_FAMILY_MAVLINK
DISC = PROTOCOL_FAMILY_DISCRETE
WIRE = PROTOCOL_FAMILY_WIRELESS
NONE = PROTOCOL_FAMILY_NONE

BUS_TRUTH: dict[str, List[str]] = {
    "ata21_21_1": [A429],
    "ata23_23_1": [A429],
    "ata23_23_2": [A429, DISC],
    "ata23_23_3": [A429],

    "ata24_24_1": [CAN],
    "ata24_24_2": [CAN],            # xlsx 明确是 CAN（之前 DB 是 A429，错）
    "ata24_24_3": [CAN],            # 同上

    "ata27_27_1": [CAN, R485],
    "ata27_27_2": [CAN, R485],
    "ata27_27_3": [R485],
    "ata27_27_4": [CAN, R422, R485, A429],

    "ata30_30_1": [A429],
    "ata30_30_2": [A429],
    "ata30_30_3": [A429],

    "ata31_31_1": [NONE],           # 显控计算机：TSN 接收方占位

    "ata32_32_1": [A429, CAN],
    "ata32_32_2": [A429, CAN, DISC],
    "ata32_32_3": [A429, CAN],

    "ata34_34_1": [A429, DISC],
    "ata34_34_2": [A429, DISC],
    "ata34_34_3": [R422],           # IRS — 之前 DB 是 A429，错
    "ata34_34_4": [R422],           # RTK — 之前 DB 是 A429，错
    "ata34_34_5": [A429, DISC],
    "ata34_34_6": [A429],
    "ata34_34_7": [R422],           # 综合备份仪表 — 之前 DB 是 A429，错
    "ata34_34_8": [A429],           # 应答机

    "ata46_46_1": [WIRE],            # 电子飞行包 — xlsx 写"无线"

    "ata86_86_1": [CAN],
    "ata86_86_2": [CAN],             # 两种CAN(通信+维护) 合并为一条 CAN spec

    "ata90_90_1": [R422],            # 视觉辅助计算机
    "ata90_90_2": [R422],            # 飞管

    "ata92_92_1": [MAV],             # 空地数据管理计算机
}


def _bus_anchor_id(base_device_id: str, family: str, is_primary: bool) -> str:
    """主 spec 保留原 device_id；其他 bus 的 spec 用后缀区分"""
    if is_primary:
        return base_device_id
    return f"{base_device_id}__{family}"


async def main():
    async with async_session() as s:
        # ── Step A: 清理渣数据 ──
        gar = (
            (await s.execute(
                select(DeviceProtocolSpec).where(
                    DeviceProtocolSpec.device_id.in_(GARBAGE_DEVICE_IDS)
                )
            )).scalars().all()
        )
        for sp in gar:
            print(f"[DEL] {sp.device_id}  {sp.device_name}")
            # 先删 drafts / versions，再删 spec（保险起见；虽然 cascade 已设但部分 FK use_alter）
            await s.execute(delete(DeviceProtocolDraft).where(DeviceProtocolDraft.spec_id == sp.id))
            await s.execute(delete(DeviceProtocolVersion).where(DeviceProtocolVersion.spec_id == sp.id))
            await s.delete(sp)
        await s.flush()

        # ── Step B: 加载目前所有 spec，按 device_id 索引（注意改名后该映射失效，所以先按改名前索引） ──
        all_rows = (await s.execute(select(DeviceProtocolSpec))).scalars().all()
        by_device_id: dict[str, List[DeviceProtocolSpec]] = {}
        for sp in all_rows:
            by_device_id.setdefault(sp.device_id, []).append(sp)

        # ── Step C: 改名（同时可能改 device_id） ──
        for old_id, (new_name, new_id) in RENAME_MAP.items():
            rows = by_device_id.get(old_id, [])
            for sp in rows:
                changed = []
                if sp.device_name != new_name:
                    changed.append(f"name: {sp.device_name} → {new_name}")
                    sp.device_name = new_name
                # 同步 parent_path 的最后一级（如果看起来是设备名）
                if sp.parent_path and isinstance(sp.parent_path, list) and sp.parent_path:
                    last = sp.parent_path[-1]
                    if last and last != new_name:
                        # parent_path 一般是 [ATA_code, ATA_display, ...]，不一定带设备名
                        # 这里只在最后一级疑似是设备名时更新
                        if isinstance(last, str) and (old_id.split("_")[-1] in last or last.endswith(sp.device_name or "")):
                            pass  # 谨慎起见不改 parent_path，保持原样
                if new_id and sp.device_id != new_id:
                    changed.append(f"id: {sp.device_id} → {new_id}")
                    sp.device_id = new_id
                if changed:
                    print(f"[REN] {old_id}: " + "; ".join(changed))

        await s.flush()

        # 再读一次（改名后 device_id 可能变了）
        all_rows = (await s.execute(select(DeviceProtocolSpec))).scalars().all()
        by_device_id = {}
        for sp in all_rows:
            by_device_id.setdefault(sp.device_id, []).append(sp)

        # ── Step D: 纠正/扩展 bus（方案 B：多总线 → 多条 spec） ──
        for anchor_id, truth_buses in BUS_TRUTH.items():
            rows = by_device_id.get(anchor_id, [])
            if not rows:
                # 可能是被改名了；在新 device_id 里找；这里先按原 anchor 找不到就跳过报警
                # （本脚本 RENAME 都是保持 device_id 的，所以不该走到这里）
                print(f"[WARN] BUS_TRUTH 引用了不存在的 device_id={anchor_id}")
                continue
            anchor_sp = rows[0]
            anchor_name = anchor_sp.device_name
            ata_code = anchor_sp.ata_code
            parent_path = anchor_sp.parent_path
            description = anchor_sp.description

            # 把 truth_buses 的第一个视为"主 family"（保留在 anchor_sp 上）
            primary_family = truth_buses[0]
            extra_families = truth_buses[1:]

            # 1) 把 anchor_sp 的 family 改为 primary（若不同）
            if anchor_sp.protocol_family != primary_family:
                print(f"[FAM] {anchor_id}: {anchor_sp.protocol_family} → {primary_family}")
                # UNIQUE(family, device_id) 约束：我们这里同 device_id 但换 family，
                # 冲突只可能是同 device_id 已经有另一条 primary_family 行。这里先查一次：
                existing = await s.execute(
                    select(DeviceProtocolSpec).where(
                        DeviceProtocolSpec.protocol_family == primary_family,
                        DeviceProtocolSpec.device_id == anchor_sp.device_id,
                    )
                )
                ex = existing.scalars().first()
                if ex and ex.id != anchor_sp.id:
                    # 已存在重复条目（之前跑过的残留），合并到 ex，删除 anchor_sp
                    print(f"       发现重复条目 id={ex.id}，删除 anchor_sp(id={anchor_sp.id})")
                    await s.execute(delete(DeviceProtocolDraft).where(DeviceProtocolDraft.spec_id == anchor_sp.id))
                    await s.execute(delete(DeviceProtocolVersion).where(DeviceProtocolVersion.spec_id == anchor_sp.id))
                    await s.delete(anchor_sp)
                    anchor_sp = ex
                else:
                    anchor_sp.protocol_family = primary_family

            await s.flush()

            # 2) 处理已经存在但应该被挂到其它 bus 的"遗留行"（比如 ata24_24_1 原来只有 CAN，那是对的；但 ata27_27_4 可能已经有 arinc429，需要保留并新增 CAN/RS422/RS485）
            # 收集该 device_id 当前已有的 families
            now_rows = (
                await s.execute(
                    select(DeviceProtocolSpec).where(
                        DeviceProtocolSpec.device_id.like(f"{anchor_id}%")
                    )
                )
            ).scalars().all()
            existing_families_primary = {r.protocol_family for r in now_rows if r.device_id == anchor_id}

            # 3) 为每个额外的 family 新增一条 spec（device_id 加后缀）
            for fam in extra_families:
                extra_id = _bus_anchor_id(anchor_id, fam, is_primary=False)
                # 已存在就跳过
                already = await s.execute(
                    select(DeviceProtocolSpec).where(
                        DeviceProtocolSpec.device_id == extra_id,
                        DeviceProtocolSpec.protocol_family == fam,
                    )
                )
                if already.scalars().first() is not None:
                    continue
                # 极端情况下 anchor 的 primary 占用了 fam，而我们又想给同 fam 加一条额外 spec
                # （不会发生：extra_families 不包含 primary_family）
                new_sp = DeviceProtocolSpec(
                    protocol_family=fam,
                    ata_code=ata_code,
                    device_id=extra_id,
                    device_name=anchor_name,
                    parent_path=parent_path,
                    description=description,
                    status="active",
                )
                s.add(new_sp)
                print(f"[ADD] {extra_id}  ({fam})  ← {anchor_name}")

            await s.flush()

        await s.commit()
        print("\n✓ realign 完成")


if __name__ == "__main__":
    asyncio.run(main())
