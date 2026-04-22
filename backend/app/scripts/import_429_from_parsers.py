# -*- coding: utf-8 -*-
"""一次性脚本：把平台里已有的 ARINC429 parser 模块 _LABEL_DEFS 导入到
DeviceProtocolVersion.spec_json，让设备协议版本管理页面能看到真实 labels。

规则（按用户决策）：
- 已有 version 的 spec → in-place 覆盖"最新版"的 spec_json（不新增版本号，保留老 version_name）
- 空壳 spec          → 新建 V1.0，availability_status=PendingCode
- created_by="import"，description="从平台 parser 模块 <xxx>_parser.py 自动导入"

要跑：
    docker exec -w /app tsn-backend python -m app.scripts.import_429_from_parsers
"""
from __future__ import annotations

import asyncio
import importlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from app.database import async_session
from app.models import DeviceProtocolSpec, DeviceProtocolVersion


# ── parser_family → 平台 parser 模块 & _LABEL_DEFS ──────────────────────
# 27-4-飞控(fcc) 暂不处理：fcc_parser 里不是 429 label 结构
# bpcu_empc/bms270v/bms800v/mcu/fms_* 这些不是 429，跳过
PARSER_MAP: Dict[str, Tuple[str, str]] = {
    "atg":   ("app.services.parsers.atg_cpe_parser",    "_LABEL_DEFS"),
    "ra":    ("app.services.parsers.ra_parser",         "_LABEL_DEFS"),
    "adc":   ("app.services.parsers.adc_parser",        "_LABEL_DEFS"),
    "lgcu":  ("app.services.parsers.lgcu_parser",       "_LABEL_DEFS"),
    "turn":  ("app.services.parsers.turn_parser",       "_LABEL_DEFS"),
    "brake": ("app.services.parsers.brake_parser",      "_LABEL_DEFS"),
    "xpdr":  ("app.services.parsers.jzxpdr113b_parser", "_LABEL_DEFS"),
}


# ── 编码类型映射：parser 的 enc → spec_json 的 ssm_type ──
def _enc_to_ssm(enc: str) -> str:
    enc = (enc or "").lower()
    if enc == "bnr":
        return "bnr"
    if enc in ("discrete", "disc"):
        return "discrete"
    if enc.startswith("bcd"):
        return "bcd"
    return "bnr"


def _build_label_entry(label_oct_int: int, defn: Dict[str, Any]) -> Dict[str, Any]:
    """把 parser 的 _LABEL_DEFS 单条转成 spec_json.labels 的一条"""
    oct_str = oct(label_oct_int)[2:].zfill(3)
    enc = (defn.get("enc") or "").lower()
    ssm = _enc_to_ssm(enc)

    entry: Dict[str, Any] = {
        "label_oct": oct_str,
        "label_dec": label_oct_int,
        "name": defn.get("cn") or defn.get("col") or f"Label {oct_str}",
        "direction": "",
        "sources": [],
        "sdi": None,
        "ssm_type": ssm,
        "data_type": enc.upper() if enc else "",
        "unit": defn.get("unit") or "",
        "range_desc": None,
        "resolution": defn.get("lsb_val"),
        "reserved_bits": "",
        "notes": "",
        "discrete_bits": {},
        "special_fields": [],
        "bnr_fields": [],
    }

    # 不同编码补充细节
    if ssm == "bnr":
        lsb_bit = defn.get("lsb_bit")
        msb_bit = defn.get("msb_bit")
        signed = defn.get("signed")
        if lsb_bit is not None and msb_bit is not None:
            entry["bnr_fields"] = [
                {
                    "name": defn.get("col") or "value",
                    "data_bits": [int(lsb_bit), int(msb_bit)],
                    "encoding": "bnr",
                    "sign_bit": int(msb_bit) if signed else None,
                    "resolution": defn.get("lsb_val"),
                    "unit": defn.get("unit") or "",
                }
            ]
        entry["notes"] = (
            f"col={defn.get('col')}; lsb_bit={lsb_bit}; msb_bit={msb_bit}; "
            f"signed={signed}; lsb_val={defn.get('lsb_val')}"
        )
    elif ssm == "discrete":
        bits = defn.get("bits")
        if isinstance(bits, (list, tuple)) and len(bits) == 2:
            a, b = int(bits[0]), int(bits[1])
            lo, hi = min(a, b), max(a, b)
            entry["discrete_bits"] = {str(i): "" for i in range(lo, hi + 1)}
            entry["notes"] = f"col={defn.get('col')}; bits range {lo}..{hi}"
        else:
            entry["notes"] = f"col={defn.get('col')}; discrete"
    elif ssm == "bcd":
        entry["notes"] = f"col={defn.get('col')}; enc={enc}"
    return entry


def _build_spec_json(
    *,
    device_name: str,
    device_id: str,
    ata_code: Optional[str],
    parser_module: str,
    label_defs: Dict[int, Dict[str, Any]],
    version_name: str,
) -> Dict[str, Any]:
    """组装完整 spec_json（protocol_meta / device_meta_ref / version_info / labels）"""
    labels_out: List[Dict[str, Any]] = []
    for lbl_int, defn in label_defs.items():
        if not isinstance(defn, dict):
            continue
        labels_out.append(_build_label_entry(int(lbl_int), defn))
    labels_out.sort(key=lambda x: x["label_dec"])

    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return {
        "protocol_meta": {
            "name": device_name,
            "version": version_name,
            "description": f"从平台 parser 模块 {parser_module} 自动导入",
            "generated_at": now_iso,
            "source": parser_module,
        },
        "device_meta_ref": {
            "device_id": device_id,
            "ata_code": ata_code,
        },
        "version_info": {
            "version": version_name,
            "created_at": now_iso,
        },
        "labels": labels_out,
    }


async def _load_label_defs(parser_family: str) -> Optional[Dict[int, Dict[str, Any]]]:
    if parser_family not in PARSER_MAP:
        return None
    mod_name, attr = PARSER_MAP[parser_family]
    try:
        m = importlib.import_module(mod_name)
    except Exception as e:
        print(f"  [WARN] 无法 import {mod_name}: {e}")
        return None
    defs = getattr(m, attr, None)
    if not isinstance(defs, dict) or not defs:
        print(f"  [WARN] {mod_name}.{attr} 为空或格式不对")
        return None
    return defs


async def main() -> None:
    async with async_session() as db:
        # 拉所有 429 spec
        res = await db.execute(
            select(DeviceProtocolSpec).where(
                DeviceProtocolSpec.protocol_family == "arinc429"
            )
        )
        specs = list(res.scalars().all())
        print(f"共有 {len(specs)} 条 429 spec，开始扫描…\n")

        summary: List[str] = []
        for s in specs:
            hints = s.parser_family_hints or []
            # 找到第一个能被我们识别的 hint
            target_family = next((h for h in hints if h in PARSER_MAP), None)
            if not target_family:
                reason = "no parser hint" if not hints else f"hints={hints} 无可导 parser"
                summary.append(f"  SKIP [{s.device_id}] {s.device_name}  ({reason})")
                continue

            defs = await _load_label_defs(target_family)
            if not defs:
                summary.append(
                    f"  SKIP [{s.device_id}] {s.device_name}  (parser load failed)"
                )
                continue

            mod_name = PARSER_MAP[target_family][0]

            # 查该 spec 最新版本
            vres = await db.execute(
                select(DeviceProtocolVersion)
                .where(DeviceProtocolVersion.spec_id == s.id)
                .order_by(DeviceProtocolVersion.version_seq.desc())
            )
            latest: Optional[DeviceProtocolVersion] = vres.scalars().first()

            if latest is None:
                # 新建 V1.0
                spec_json = _build_spec_json(
                    device_name=s.device_name,
                    device_id=s.device_id,
                    ata_code=s.ata_code,
                    parser_module=mod_name,
                    label_defs=defs,
                    version_name="V1.0",
                )
                v = DeviceProtocolVersion(
                    spec_id=s.id,
                    version_name="V1.0",
                    version_seq=1,
                    description=f"从平台 parser 模块 {mod_name.split('.')[-1]}.py 自动导入",
                    spec_json=spec_json,
                    availability_status="PendingCode",
                    created_by="import",
                    created_at=datetime.utcnow(),
                )
                db.add(v)
                summary.append(
                    f"  NEW  [{s.device_id}] {s.device_name}  → V1.0 (PendingCode), {len(spec_json['labels'])} labels"
                )
            else:
                # 覆盖最新版
                old_ct = len((latest.spec_json or {}).get("labels") or [])
                spec_json = _build_spec_json(
                    device_name=s.device_name,
                    device_id=s.device_id,
                    ata_code=s.ata_code,
                    parser_module=mod_name,
                    label_defs=defs,
                    version_name=latest.version_name,
                )
                latest.spec_json = spec_json
                # 标记一下 description，让历史可追溯
                latest.description = (
                    f"[{datetime.utcnow().date()} 重新导入] "
                    f"从平台 parser 模块 {mod_name.split('.')[-1]}.py 自动导入"
                )
                summary.append(
                    f"  OVER [{s.device_id}] {s.device_name}  → {latest.version_name} "
                    f"覆盖 (labels: {old_ct} → {len(spec_json['labels'])})"
                )

        await db.commit()
        print("=== 导入结果 ===")
        for line in summary:
            print(line)
        print("\n✅ done.")


if __name__ == "__main__":
    asyncio.run(main())
