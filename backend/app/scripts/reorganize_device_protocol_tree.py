"""设备协议树重组脚本（幂等）

按 2026-04 与用户对齐的决策，把 DB 中的设备协议树调整到"每一个 spec =
一份真实的协议文档"的形态。每一步都会输出 SKIP / DO / DONE，重复运行安全。

变更清单：
  1) 新增 2 条 spec（用户确认的"一设备多协议"拆分）
       - ata90_90_2__ins_init   rs422   "90-2 飞管 (惯导初始化)"
       - ata92_92_1__stat       mavlink "92-1 空地数据统计"

  2) 重命名 2 条 spec 的 device_name
       - ata90_90_2  → "90-2 飞管 (与飞控)"
       - ata92_92_1  → "92-1 空地通信协议"

  3) 重命名 3 个版本号（把时间戳风格改成 V1.0）
       - ata23_23_3      V20260402 → V1.0
       - ata34_34_8      V20260113 → V1.0
       - ata24_24_3      V2.0      → V1.0
         （24-3 PDU 的"V2.0"其实是文档里误标，实际只有 V1.0 一版）

  4) 按目标版本清单对各 spec 做版本对齐（新增空壳版本）
       - 空壳 = Arinc429/Can/Rs422 family handler 的 normalize({}) 结果
       - availability_status = Available（可选池，待 parser 实现再推进）
       - git_export_status   = pending（留给 M2 真 Git 后端处理）

  5) 32-1 刹车控制单元仅 ARINC429：删除历史上误绑的 ``ata32_32_1__can`` spec
"""
import asyncio
import copy
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_PENDING_CODE,
    DEVICE_SPEC_ACTIVE,
    DeviceProtocolSpec,
    DeviceProtocolVersion,
    GIT_EXPORT_PENDING,
)
from app.services.protocol_family import get_family_handler


# ── 目标清单 ──
# (device_id, protocol_family) -> {
#     "device_name": 展示名,
#     "ata_code":    ATA 系统码,
#     "parent_path": 父级路径,
#     "versions":    按序的版本名列表（有序，前面的 seq 小）
# }
TARGET: Dict[Tuple[str, str], Dict] = {
    # ATA21
    ("ata21_21_1", "arinc429"): {
        "device_name": "21-1-通风系统", "ata_code": "ata21",
        "parent_path": ["ATA21", "空调系统"],
        "versions": ["V1.0"],
    },
    # ATA23
    ("ata23_23_1", "arinc429"): {
        "device_name": "23-1-AMU", "ata_code": "ata23",
        "parent_path": ["ATA23", "通信系统"], "versions": ["V1.0"],
    },
    ("ata23_23_2", "arinc429"): {
        "device_name": "23-2-ELT发射器", "ata_code": "ata23",
        "parent_path": ["ATA23", "通信系统"], "versions": ["V1.0"],
    },
    ("ata23_23_3", "arinc429"): {
        "device_name": "23-3-5GATG", "ata_code": "ata23",
        "parent_path": ["ATA23", "通信系统"], "versions": ["V1.0"],
    },
    # ATA24
    ("ata24_24_1", "can"): {
        "device_name": "24-1-270V&28V BMS", "ata_code": "ata24",
        "parent_path": ["ATA24", "电源系统"],
        "versions": ["V2.0", "V2.4", "V2.5", "V2.5.1", "V2.5.2"],
    },
    ("ata24_24_2", "can"): {
        "device_name": "24-2-配电盘箱", "ata_code": "ata24",
        "parent_path": ["ATA24", "电源系统"],
        "versions": ["V1.0", "V1.1", "V2.0", "V2.1", "V3.0", "V4.0"],
    },
    ("ata24_24_3", "can"): {
        "device_name": "24-3-高压配电单元PDU", "ata_code": "ata24",
        "parent_path": ["ATA24", "电源系统"], "versions": ["V1.0"],
    },
    # ATA27
    ("ata27_27_1", "arinc429"): {
        "device_name": "27-1-主飞控作动", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"],
        "versions": ["V1.0", "V1.5", "V1.7", "V1.8", "V2.0"],
    },
    ("ata27_27_2", "arinc429"): {
        "device_name": "27-2-高升力作动", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"],
        "versions": ["V2.0", "V3.0", "V4.0"],
    },
    ("ata27_27_3", "rs485"): {
        "device_name": "27-3-DMRS", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"], "versions": ["V1.0"],
    },
    ("ata27_27_4", "can"): {
        "device_name": "27-4-飞控计算机", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"], "versions": ["V13.4"],
    },
    ("ata27_27_4__arinc429", "arinc429"): {
        "device_name": "27-4-飞控计算机", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"], "versions": ["V13.4"],
    },
    ("ata27_27_4__rs422", "rs422"): {
        "device_name": "27-4-飞控计算机", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"], "versions": ["V13.4"],
    },
    ("ata27_27_4__rs485", "rs485"): {
        "device_name": "27-4-飞控计算机", "ata_code": "ata27",
        "parent_path": ["ATA27", "飞行控制系统"], "versions": ["V13.4"],
    },
    # ATA30
    ("ata30_30_1", "arinc429"): {
        "device_name": "30-1-防除冰系统控制器", "ata_code": "ata30",
        "parent_path": ["ATA30", "防除冰和除雨系统"], "versions": ["V1.0", "V2.0"],
    },
    ("ata30_30_2", "arinc429"): {
        "device_name": "30-2-风挡雨刷马达", "ata_code": "ata30",
        "parent_path": ["ATA30", "防除冰和除雨系统"], "versions": ["V1.0", "V2.0"],
    },
    ("ata30_30_3", "arinc429"): {
        "device_name": "30-3-风挡加热控制器", "ata_code": "ata30",
        "parent_path": ["ATA30", "防除冰和除雨系统"], "versions": ["V1.0"],
    },
    # ATA31
    ("ata31_31_1", "none"): {
        "device_name": "31-1-显控计算机", "ata_code": "ata31",
        "parent_path": ["ATA31", "指示记录系统"], "versions": ["V1.0"],
    },
    # ATA32 刹车只留 V7.3
    ("ata32_32_1", "arinc429"): {
        "device_name": "32-1-刹车控制单元", "ata_code": "ata32",
        "parent_path": ["ATA32", "起落架系统"], "versions": ["V7.3"],
    },
    ("ata32_32_2", "arinc429"): {
        "device_name": "32-2-收放控制单元", "ata_code": "ata32",
        "parent_path": ["ATA32", "起落架系统"],
        "versions": ["V1.0", "V1.1", "V2.0", "V3.0", "V4.0", "wyrV9"],
    },
    ("ata32_32_3", "arinc429"): {
        "device_name": "32-3-转弯控制单元", "ata_code": "ata32",
        "parent_path": ["ATA32", "起落架系统"],
        "versions": ["V1.0", "V1.1", "V2.0", "V3.0", "V4.0", "V5.0", "V6.0"],
    },
    # ATA34
    ("ata34_34_1", "arinc429"): {
        "device_name": "34-1-无线电高度表(RA)收发机", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.0"],
    },
    ("ata34_34_2", "arinc429"): {
        "device_name": "34-2-ADC（大气数据计算机）", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"],
        "versions": ["V2.0", "V2.1", "V2.2"],
    },
    ("ata34_34_3", "rs422"): {
        "device_name": "34-3-IRS（惯性基准系统）", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"],
        "versions": ["V1.0", "V2.0", "V3.0"],
    },
    ("ata34_34_4", "rs422"): {
        "device_name": "34-4-RTK机载接收机", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.4"],
    },
    ("ata34_34_5", "arinc429"): {
        "device_name": "34-5-甚高频通信及无线电导航集成设备", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.0"],
    },
    ("ata34_34_6", "arinc429"): {
        "device_name": "34-6-北斗导航接收机", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.0"],
    },
    ("ata34_34_7", "rs422"): {
        "device_name": "34-7-综合备份仪表", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.0"],
    },
    ("ata34_34_8", "arinc429"): {
        "device_name": "34-8-应答机", "ata_code": "ata34",
        "parent_path": ["ATA34", "导航系统"], "versions": ["V1.0"],
    },
    # ATA46
    ("ata46_46_1", "wireless"): {
        "device_name": "46-1-电子飞行包", "ata_code": "ata46",
        "parent_path": ["ATA46", "信息系统"], "versions": ["V1.0"],
    },
    # ATA52
    ("ata52_52_1", "discrete"): {
        "device_name": "52-舱门控制系统", "ata_code": "ata52",
        "parent_path": ["ATA52", "舱门系统"], "versions": ["V1.0"],
    },
    # ATA86
    ("ata86_86_1", "can"): {
        "device_name": "86-1-电驱", "ata_code": "ata86",
        "parent_path": ["ATA86", "电推进系统"],
        "versions": ["V1.0", "V1.1", "V2.0", "V3.0", "V4.0", "V5.0"],
    },
    ("ata86_86_2", "can"): {
        "device_name": "86-2-动力电池800V BMS", "ata_code": "ata86",
        "parent_path": ["ATA86", "电推进系统"],
        "versions": ["V2.0", "V2.4", "V2.5.1"],
    },
    # ATA90 飞管：★ 2 协议
    ("ata90_90_1", "rs422"): {
        "device_name": "90-1-视觉辅助计算机", "ata_code": "ata90",
        "parent_path": ["ATA90", "自主飞行系统"], "versions": ["V1.0"],
    },
    ("ata90_90_2", "rs422"): {
        "device_name": "90-2 飞管 (与飞控)", "ata_code": "ata90",
        "parent_path": ["ATA90", "自主飞行系统"],
        "versions": ["V1.0", "V1.1", "V1.2", "V1.3", "V1.4", "V1.5"],
    },
    ("ata90_90_2__ins_init", "rs422"): {
        "device_name": "90-2 飞管 (惯导初始化)", "ata_code": "ata90",
        "parent_path": ["ATA90", "自主飞行系统"],
        "versions": ["V0.1", "V0.2", "V0.3.1"],
    },
    # ATA92：★ 2 协议
    ("ata92_92_1", "mavlink"): {
        "device_name": "92-1 空地通信协议", "ata_code": "ata92",
        "parent_path": ["ATA92", "地面网联系统"], "versions": ["V1.1"],
    },
    ("ata92_92_1__stat", "mavlink"): {
        "device_name": "92-1 空地数据统计", "ata_code": "ata92",
        "parent_path": ["ATA92", "地面网联系统"], "versions": ["V1.0"],
    },
}


# ── 版本重命名计划 ──
# 按 (device_id, family, old_name, new_name)
VERSION_RENAMES: List[Tuple[str, str, str, str]] = [
    ("ata23_23_3", "arinc429", "V20260402", "V1.0"),
    ("ata34_34_8", "arinc429", "V20260113", "V1.0"),
    ("ata24_24_3", "can", "V2.0", "V1.0"),
]

# 已从目标树移除：历史上与「32-1-刹车控制单元」误绑的 CAN spec（该设备仅 429）
RETIRED_SPEC_KEYS: List[Tuple[str, str]] = [
    ("ata32_32_1__can", "can"),
]


def _log(op: str, status: str, msg: str) -> None:
    sign = {"SKIP": "○", "DO": "▶", "DONE": "✓", "WARN": "!"}.get(status, " ")
    print(f"  [{status:<4}] {sign} {op}: {msg}")


def _build_empty_spec(family: str, device_name: str, version_name: str) -> Dict:
    """空壳 spec = family normalize({}) + protocol_meta 基本信息"""
    handler = get_family_handler(family)
    spec = handler.normalize_spec({})
    meta = spec.setdefault("protocol_meta", {})
    meta["name"] = device_name
    meta["version"] = version_name
    meta["description"] = "空壳版本：占位版本号，待 parser 实现/协议正文导入后补全。"
    return spec


async def step1_rename_devices(db) -> None:
    """Step 1: 重命名 2 个 spec 的 device_name"""
    print("\n── Step 1: 重命名 device_name ──")
    targets = [
        ("ata90_90_2", "rs422", "90-2 飞管 (与飞控)"),
        ("ata92_92_1", "mavlink", "92-1 空地通信协议"),
    ]
    for did, fam, new_name in targets:
        r = await db.execute(
            select(DeviceProtocolSpec).where(
                DeviceProtocolSpec.device_id == did,
                DeviceProtocolSpec.protocol_family == fam,
            )
        )
        spec = r.scalar_one_or_none()
        if spec is None:
            _log("rename_device", "WARN", f"{did}[{fam}] 不存在，跳过")
            continue
        if spec.device_name == new_name:
            _log("rename_device", "SKIP", f"{did}[{fam}] 已是 '{new_name}'")
            continue
        old = spec.device_name
        spec.device_name = new_name
        _log("rename_device", "DONE", f"{did}[{fam}] '{old}' → '{new_name}'")
    await db.flush()


async def step2_rename_versions(db) -> None:
    """Step 2: 重命名 3 个版本号"""
    print("\n── Step 2: 重命名版本号 ──")
    for did, fam, old, new in VERSION_RENAMES:
        r = await db.execute(
            select(DeviceProtocolSpec).where(
                DeviceProtocolSpec.device_id == did,
                DeviceProtocolSpec.protocol_family == fam,
            )
        )
        spec = r.scalar_one_or_none()
        if spec is None:
            _log("rename_version", "WARN", f"{did}[{fam}] spec 不存在")
            continue
        vr = await db.execute(
            select(DeviceProtocolVersion).where(
                DeviceProtocolVersion.spec_id == spec.id,
                DeviceProtocolVersion.version_name == old,
            )
        )
        ver = vr.scalar_one_or_none()
        if ver is None:
            # 已经改过？看 new 名字是否存在
            vr2 = await db.execute(
                select(DeviceProtocolVersion).where(
                    DeviceProtocolVersion.spec_id == spec.id,
                    DeviceProtocolVersion.version_name == new,
                )
            )
            if vr2.scalar_one_or_none():
                _log("rename_version", "SKIP", f"{did}[{fam}] '{old}' 已改为 '{new}'")
            else:
                _log("rename_version", "WARN", f"{did}[{fam}] 版本 '{old}' 不存在")
            continue
        ver.version_name = new
        # spec_json.protocol_meta.version 也同步
        sj = copy.deepcopy(ver.spec_json or {})
        sj.setdefault("protocol_meta", {})["version"] = new
        ver.spec_json = sj
        _log("rename_version", "DONE", f"{did}[{fam}] '{old}' → '{new}'")
    await db.flush()


async def step3_create_specs(db) -> None:
    """Step 3: 对目标清单里所有 (device_id, family) 组合，若 DB 里没有就建 spec。

    包含：
      - 用户确认的拆分：ata90_90_2__ins_init / ata92_92_1__stat
      - 目标里有但 DB 里缺的（如 27-1/27-2 arinc429、52-1 discrete）
    """
    print("\n── Step 3: 新建/补齐 spec ──")
    for (did, fam), meta in TARGET.items():
        r = await db.execute(
            select(DeviceProtocolSpec).where(
                DeviceProtocolSpec.device_id == did,
                DeviceProtocolSpec.protocol_family == fam,
            )
        )
        if r.scalar_one_or_none():
            continue
        spec = DeviceProtocolSpec(
            protocol_family=fam,
            device_id=did,
            device_name=meta["device_name"],
            ata_code=meta["ata_code"],
            parent_path=meta["parent_path"],
            description="",
            status=DEVICE_SPEC_ACTIVE,
            created_by="reorg_script",
        )
        db.add(spec)
        _log("create_spec", "DONE", f"{did}[{fam}] '{meta['device_name']}'")
    await db.flush()


async def step4_ensure_versions(db) -> None:
    """Step 4: 对目标清单里的每个 spec，按 versions 对齐（补空壳）"""
    print("\n── Step 4: 版本对齐（新增空壳）──")
    for (did, fam), meta in TARGET.items():
        r = await db.execute(
            select(DeviceProtocolSpec)
            .where(
                DeviceProtocolSpec.device_id == did,
                DeviceProtocolSpec.protocol_family == fam,
            )
            .options(selectinload(DeviceProtocolSpec.versions))
        )
        spec = r.scalar_one_or_none()
        if spec is None:
            _log("ensure_version", "WARN", f"{did}[{fam}] spec 不存在，跳过")
            continue
        existing_names = {v.version_name for v in spec.versions}
        max_seq = max((v.version_seq for v in spec.versions), default=0)
        for idx, vname in enumerate(meta["versions"]):
            if vname in existing_names:
                _log("ensure_version", "SKIP", f"{did}[{fam}] '{vname}' 已存在")
                continue
            max_seq += 1
            spec_json = _build_empty_spec(fam, spec.device_name, vname)
            version = DeviceProtocolVersion(
                spec_id=spec.id,
                version_name=vname,
                version_seq=max_seq,
                description=f"[reorg_script] 按目标清单补入空壳版本 {vname}",
                spec_json=spec_json,
                availability_status=AVAILABILITY_AVAILABLE,
                git_export_status=GIT_EXPORT_PENDING,
                created_by="reorg_script",
            )
            db.add(version)
            _log("ensure_version", "DONE", f"{did}[{fam}] '{vname}' seq={max_seq} (空壳)")
    await db.flush()


async def step4b_remove_retired_specs(db) -> None:
    """删除 RETIRED_SPEC_KEYS 中的 spec（含级联版本/草稿）。

    用于从目标清单撤下的设备+总线组合（如刹车单元误绑 CAN）。
    """
    print("\n── Step 4b: 移除已退役 spec ──")
    for did, fam in RETIRED_SPEC_KEYS:
        r = await db.execute(
            select(DeviceProtocolSpec)
            .where(
                DeviceProtocolSpec.device_id == did,
                DeviceProtocolSpec.protocol_family == fam,
            )
            .options(selectinload(DeviceProtocolSpec.versions))
        )
        spec = r.scalar_one_or_none()
        if spec is None:
            _log("remove_retired", "SKIP", f"{did}[{fam}] 不存在")
            continue
        n_ver = len(spec.versions or [])
        # 解除自引用，避免部分 SQLite 配置下删 spec 与 version 顺序冲突
        spec.current_version_id = None
        await db.flush()
        await db.delete(spec)
        _log("remove_retired", "DONE", f"已删除 {did}[{fam}]（含约 {n_ver} 个版本）")
    await db.flush()


async def step6_prune_orphans(db) -> None:
    """Step 6: 清理孤儿 spec（目标清单之外 + 没有任何版本）

    这些通常是之前多 bus 配置的遗留空壳，数据上没有任何价值。
    """
    print("\n── Step 6: 清理孤儿 spec ──")
    r = await db.execute(
        select(DeviceProtocolSpec).options(selectinload(DeviceProtocolSpec.versions))
    )
    specs = list(r.scalars().all())
    target_keys = set(TARGET.keys())
    pruned = 0
    for s in specs:
        key = (s.device_id, s.protocol_family)
        if key in target_keys:
            continue
        if s.versions:
            _log("prune_orphan", "WARN",
                 f"{s.device_id}[{s.protocol_family}] 不在目标清单但有 {len(s.versions)} 版本，保留")
            continue
        _log("prune_orphan", "DONE", f"delete {s.device_id}[{s.protocol_family}] (no versions)")
        await db.delete(s)
        pruned += 1
    await db.flush()
    print(f"  共清理 {pruned} 条孤儿 spec")


async def step5_summary(db) -> None:
    print("\n── Step 5: 汇总 ──")
    r = await db.execute(
        select(DeviceProtocolSpec).options(selectinload(DeviceProtocolSpec.versions))
    )
    specs = sorted(r.scalars().all(), key=lambda s: (s.ata_code or "", s.device_id))
    total_specs = 0
    total_versions = 0
    total_versions_in_target = 0
    for s in specs:
        key = (s.device_id, s.protocol_family)
        in_target = key in TARGET
        marker = "★" if in_target else " "
        total_specs += 1
        total_versions += len(s.versions)
        if in_target:
            total_versions_in_target += len(s.versions)
        v_names = sorted(v.version_name for v in s.versions)
        print(f"  {marker} {s.device_id:<35} [{s.protocol_family:<10}]  "
              f"{s.device_name[:30]:<30}  versions={v_names}")
    print(f"\n  总 spec={total_specs}，总 version={total_versions}，"
          f"目标清单覆盖 version={total_versions_in_target}")


async def main():
    async with async_session() as db:
        await step1_rename_devices(db)
        await step2_rename_versions(db)
        await step3_create_specs(db)
        await step4_ensure_versions(db)
        await step4b_remove_retired_specs(db)
        await step6_prune_orphans(db)
        await db.commit()
        await step5_summary(db)
    print("\n重组完成。")


if __name__ == "__main__":
    asyncio.run(main())
