# -*- coding: utf-8 -*-
"""TSN 协议草稿服务（MR2）

只在 Draft 表上工作。clone 自 Available 版本或从 ICD Excel 新建，
并在 Draft 状态下提供端口/字段 CRUD、批量 upsert、diff、以及导出 Excel。
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import DRAFT_UPLOAD_DIR
from ..models import (
    DRAFT_SOURCE_CLONE,
    DRAFT_SOURCE_EXCEL,
    DRAFT_STATUS_DRAFT,
    DraftFieldDefinition,
    DraftPortDefinition,
    FieldDefinition,
    PortDefinition,
    Protocol,
    ProtocolVersion,
    ProtocolVersionDraft,
)


# 允许的 data_type 白名单，与 FieldDefinition 保持一致
VALID_DATA_TYPES = {
    "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64",
    "float32", "float64",
    "bytes", "string",
}

VALID_DATA_DIRECTIONS = {"uplink", "downlink", "network"}

# 端口级可变字段白名单（共享给 clone / add / update / bulk_upsert）
# 前 9 项是已有核心列；后 11 项是 ICD 6.0.x 扩展列
PORT_MUTABLE_ATTRS = (
    "message_name",
    "source_device",
    "target_device",
    "multicast_ip",
    "data_direction",
    "period_ms",
    "description",
    "protocol_family",
    "port_role",
    # ── ICD 扩展 ──
    "message_id",
    "source_interface_id",
    "port_id_label",
    "diu_id",
    "diu_id_set",
    "diu_recv_mode",
    "tsn_source_ip",
    "diu_ip",
    "dataset_path",
    "data_real_path",
    "final_recv_device",
)


class DraftStateError(Exception):
    """对非 draft 状态的草稿做写操作时抛"""


class DraftNotFoundError(Exception):
    pass


class ProtocolDraftService:
    """Draft 上的所有写操作统一入口"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ───── 加载 ─────
    async def get_draft(self, draft_id: int, *, with_fields: bool = True) -> ProtocolVersionDraft:
        stmt = select(ProtocolVersionDraft).where(ProtocolVersionDraft.id == draft_id)
        if with_fields:
            stmt = stmt.options(
                selectinload(ProtocolVersionDraft.ports).selectinload(DraftPortDefinition.fields)
            )
        else:
            stmt = stmt.options(selectinload(ProtocolVersionDraft.ports))
        result = await self.db.execute(stmt)
        draft = result.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"草稿 {draft_id} 不存在")
        return draft

    async def list_drafts(
        self,
        *,
        created_by: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ProtocolVersionDraft]:
        # eager-load 到 fields 这层，避免调用方序列化时触发 lazy-load（MissingGreenlet）
        stmt = select(ProtocolVersionDraft).options(
            selectinload(ProtocolVersionDraft.ports).selectinload(DraftPortDefinition.fields)
        ).order_by(ProtocolVersionDraft.updated_at.desc())
        if created_by:
            stmt = stmt.where(ProtocolVersionDraft.created_by == created_by)
        if status:
            stmt = stmt.where(ProtocolVersionDraft.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ───── 创建 ─────
    async def create_from_version(
        self,
        *,
        base_version_id: int,
        target_version: str,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> ProtocolVersionDraft:
        """从一个已有的 ProtocolVersion 深拷贝出 Draft"""
        pv_res = await self.db.execute(
            select(ProtocolVersion)
            .where(ProtocolVersion.id == base_version_id)
            .options(selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields))
        )
        pv = pv_res.scalar_one_or_none()
        if not pv:
            raise ValueError(f"基础版本 {base_version_id} 不存在")

        draft = ProtocolVersionDraft(
            protocol_id=pv.protocol_id,
            base_version_id=pv.id,
            source_type=DRAFT_SOURCE_CLONE,
            name=name,
            target_version=target_version,
            description=description or f"基于 v{pv.version} 创建",
            status=DRAFT_STATUS_DRAFT,
            created_by=created_by,
        )
        self.db.add(draft)
        await self.db.flush()

        for p in pv.ports or []:
            draft_port = DraftPortDefinition(
                draft_id=draft.id,
                port_number=p.port_number,
                **{attr: getattr(p, attr, None) for attr in PORT_MUTABLE_ATTRS},
            )
            self.db.add(draft_port)
            await self.db.flush()
            for f in p.fields or []:
                self.db.add(
                    DraftFieldDefinition(
                        draft_port_id=draft_port.id,
                        field_name=f.field_name,
                        field_offset=f.field_offset,
                        field_length=f.field_length,
                        data_type=f.data_type,
                        scale_factor=f.scale_factor,
                        unit=f.unit,
                        description=f.description,
                        byte_order=f.byte_order,
                    )
                )
        await self.db.commit()
        # 重新 eager-load 已建好的 ports / fields，避免调用方序列化触发 lazy-load（MissingGreenlet）
        return await self.get_draft(draft.id, with_fields=True)

    async def create_from_excel(
        self,
        *,
        file_bytes: bytes,
        original_filename: str,
        protocol_id: int,
        target_version: str,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Tuple[ProtocolVersionDraft, Dict[str, Any]]:
        """上传 ICD Excel 建新 Draft（整版本替换）"""
        proto_res = await self.db.execute(
            select(Protocol).where(Protocol.id == protocol_id)
        )
        protocol = proto_res.scalar_one_or_none()
        if not protocol:
            raise ValueError(f"协议 {protocol_id} 不存在")

        # 落盘，便于审批/回查
        safe_name = original_filename.replace("\\", "_").replace("/", "_")
        file_path = Path(DRAFT_UPLOAD_DIR) / f"{uuid.uuid4().hex}_{safe_name}"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        draft = ProtocolVersionDraft(
            protocol_id=protocol_id,
            base_version_id=None,
            source_type=DRAFT_SOURCE_EXCEL,
            name=name,
            target_version=target_version,
            description=description or f"从 {original_filename} 导入",
            status=DRAFT_STATUS_DRAFT,
            created_by=created_by,
            source_file_path=str(file_path),
        )
        self.db.add(draft)
        await self.db.flush()

        stats = await self._parse_icd_into_draft(draft.id, str(file_path))
        await self.db.commit()
        full_draft = await self.get_draft(draft.id, with_fields=True)
        return full_draft, stats

    async def _parse_icd_into_draft(self, draft_id: int, file_path: str) -> Dict[str, Any]:
        """解析 ICD Excel 写入 Draft 表（结构与 icd_importer 对齐，但不落正式表）"""
        xl = pd.ExcelFile(file_path)
        sheet_names = xl.sheet_names
        stats: Dict[str, Any] = {
            "sheets_processed": [],
            "ports_created": 0,
            "fields_created": 0,
            "errors": [],
        }

        for direction, keywords in (
            ("uplink", ["上行", "uplink"]),
            ("downlink", ["下行", "downlink"]),
            ("network", ["网络交互", "网络交换", "network"]),
        ):
            sheet = self._find_sheet(sheet_names, keywords)
            if not sheet:
                continue
            try:
                df = pd.read_excel(file_path, sheet_name=sheet)
                pc, fc = await self._process_sheet(df, draft_id, direction)
                stats["ports_created"] += pc
                stats["fields_created"] += fc
                stats["sheets_processed"].append(sheet)
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"处理 {sheet} 失败：{e}")
        return stats

    @staticmethod
    def _find_sheet(sheet_names: List[str], keywords: List[str]) -> Optional[str]:
        for sheet in sheet_names:
            for kw in keywords:
                if kw in sheet.lower() or kw in sheet:
                    return sheet
        return None

    @staticmethod
    def _find_column(columns, keywords: List[str]) -> Optional[str]:
        for col in columns:
            col_str = str(col)
            if any(kw in col_str for kw in keywords):
                return col
        return None

    @staticmethod
    def _find_col_exact(columns, target: str) -> Optional[str]:
        """精确匹配 ICD 原表头（忽略两端空白）"""
        t = target.strip()
        for col in columns:
            if str(col).strip() == t:
                return col
        return None

    @staticmethod
    def _norm_cell(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        # 浮点若实际为整数，去掉 .0（pandas 读取纯数字列时会强转 float）
        if isinstance(value, float):
            if value.is_integer():
                value = int(value)
        text = str(value).strip()
        if text.lower() == "nan":
            return ""
        return text

    @staticmethod
    def _guess_data_type(length: int) -> str:
        if length == 1:
            return "uint8"
        if length == 2:
            return "uint16"
        if length == 4:
            return "uint32"
        if length == 8:
            return "float64"
        return "bytes"

    @staticmethod
    def _build_source_device(direction: str, source_name: Any, target_name: Any) -> Optional[str]:
        src = ProtocolDraftService._norm_cell(source_name)
        dst = ProtocolDraftService._norm_cell(target_name)
        if direction == "uplink":
            return src or None
        if direction == "downlink":
            if src and dst:
                return f"{src}->{dst}"
            return (src or dst) or None
        return (src or dst) or None

    async def _process_sheet(
        self, df: pd.DataFrame, draft_id: int, direction: str
    ) -> Tuple[int, int]:
        # 核心列：精确 → 模糊兜底
        port_col = self._find_col_exact(df.columns, "UDP端口") or self._find_column(df.columns, ["UDP", "端口"])
        if not port_col:
            return 0, 0
        msg_col = self._find_column(df.columns, ["消息名称", "消息名"])
        source_device_col = self._find_column(
            df.columns, ["待转换TSN设备", "待转换", "源设备", "源端设备", "消息源设备名称"]
        )
        target_device_col = (
            self._find_col_exact(df.columns, "DataSet目的端设备名称")
            or self._find_col_exact(df.columns, "消息目的设备")
            or self._find_column(df.columns, ["目的端设备", "目标设备"])
        )
        desc_col = self._find_col_exact(df.columns, "备注") or self._find_column(df.columns, ["说明", "备注"])
        ip_col = self._find_col_exact(df.columns, "组播组IP") or self._find_column(df.columns, ["组播", "IP"])
        period_col = self._find_col_exact(df.columns, "消息周期") or self._find_column(df.columns, ["周期"])
        dataset_col = self._find_col_exact(df.columns, "消息内数据集") or self._find_column(df.columns, ["数据集"])
        offset_col = self._find_col_exact(df.columns, "消息内偏移") or self._find_column(df.columns, ["偏移"])
        length_col = self._find_col_exact(df.columns, "长度") or self._find_column(df.columns, ["长度"])

        # ICD 扩展列：严格精确匹配，避免 DIU编号 误中 DIU编号集合
        ext_cols_def = (
            ("message_id", "消息编号"),
            ("source_interface_id", "消息源端接口编号"),
            ("port_id_label", "PortID"),
            ("diu_id", "DIU编号"),
            ("diu_id_set", "DIU编号集合"),
            ("diu_recv_mode", "DIU消息接收形式"),
            ("tsn_source_ip", "TSN消息源端IP"),
            ("diu_ip", "承接转换的DIU IP"),
            ("dataset_path", "DataSet传递路径"),
            ("data_real_path", "数据实际路径"),
            ("final_recv_device", "最终接收端设备"),
        )
        ext_col_map: Dict[str, Optional[str]] = {
            attr: self._find_col_exact(df.columns, title) for attr, title in ext_cols_def
        }

        ports_data: Dict[int, Dict[str, Any]] = {}
        fields_data: List[Tuple[int, Dict[str, Any]]] = []
        current_port = None

        for _, row in df.iterrows():
            port_val = row.get(port_col)
            if pd.notna(port_val):
                try:
                    port_num = int(float(port_val))
                except (ValueError, TypeError):
                    continue
                current_port = port_num
                raw_source = row.get(source_device_col) if source_device_col else None
                raw_target = row.get(target_device_col) if target_device_col else None

                period_v = None
                if period_col and pd.notna(row.get(period_col)):
                    try:
                        period_v = float(row.get(period_col))
                    except (ValueError, TypeError):
                        period_v = None

                ext_values = {
                    attr: (self._norm_cell(row.get(col)) or None)
                    for attr, col in ext_col_map.items()
                    if col is not None
                }

                if current_port not in ports_data:
                    ports_data[current_port] = {
                        "port_number": current_port,
                        "message_name": self._norm_cell(row.get(msg_col)) or None if msg_col else None,
                        "source_device": self._build_source_device(direction, raw_source, raw_target),
                        "target_device": self._norm_cell(raw_target) or None,
                        "description": self._norm_cell(row.get(desc_col)) or None if desc_col else None,
                        "multicast_ip": self._norm_cell(row.get(ip_col)) or None if ip_col else None,
                        "data_direction": direction,
                        "period_ms": period_v,
                        **ext_values,
                    }
            if current_port and dataset_col and offset_col and length_col:
                fname = row.get(dataset_col)
                off = row.get(offset_col)
                ln = row.get(length_col)
                if pd.notna(fname) and pd.notna(off) and pd.notna(ln):
                    try:
                        fields_data.append(
                            (
                                current_port,
                                {
                                    "field_name": str(fname).strip(),
                                    "field_offset": int(float(off)),
                                    "field_length": int(float(ln)),
                                    "data_type": self._guess_data_type(int(float(ln))),
                                },
                            )
                        )
                    except (ValueError, TypeError):
                        pass

        # 落 Draft 表，PORT_FAMILY_MAP 兜底 protocol_family
        from .protocol_service import PORT_FAMILY_MAP
        port_count = 0
        field_count = 0
        port_id_map: Dict[int, int] = {}
        for port_num, info in ports_data.items():
            dp = DraftPortDefinition(
                draft_id=draft_id,
                protocol_family=PORT_FAMILY_MAP.get(port_num),
                **info,
            )
            self.db.add(dp)
            await self.db.flush()
            port_id_map[port_num] = dp.id
            port_count += 1

        seen_field_keys: set[Tuple[int, str]] = set()
        for port_num, finfo in fields_data:
            if port_num not in port_id_map:
                continue
            key = (port_id_map[port_num], finfo["field_name"])
            if key in seen_field_keys:
                # 同端口同字段名重复，跳过第二条
                continue
            seen_field_keys.add(key)
            self.db.add(DraftFieldDefinition(draft_port_id=port_id_map[port_num], **finfo))
            field_count += 1
        await self.db.flush()
        return port_count, field_count

    # ───── 状态守卫 ─────
    @staticmethod
    def _ensure_editable(draft: ProtocolVersionDraft):
        if draft.status != DRAFT_STATUS_DRAFT:
            raise DraftStateError(
                f"草稿当前状态为 {draft.status}，不可编辑（仅 draft 态可写）"
            )

    # ───── 草稿元数据 ─────
    async def update_draft_meta(
        self,
        draft_id: int,
        *,
        name: Optional[str] = None,
        target_version: Optional[str] = None,
        description: Optional[str] = None,
    ) -> ProtocolVersionDraft:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        if name is not None:
            draft.name = name
        if target_version is not None:
            draft.target_version = target_version
        if description is not None:
            draft.description = description
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(draft)
        return draft

    async def delete_draft(self, draft_id: int):
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        await self.db.delete(draft)
        await self.db.commit()

    # ───── 端口 CRUD ─────
    async def add_port(self, draft_id: int, payload: Dict[str, Any]) -> DraftPortDefinition:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        port_number = int(payload["port_number"])
        exists = any(p.port_number == port_number for p in draft.ports)
        if exists:
            raise ValueError(f"端口 {port_number} 在草稿中已存在")
        dp = DraftPortDefinition(
            draft_id=draft.id,
            port_number=port_number,
            **{attr: payload.get(attr) for attr in PORT_MUTABLE_ATTRS},
        )
        self.db.add(dp)
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(dp)
        return dp

    async def update_port(self, draft_id: int, port_id: int, payload: Dict[str, Any]) -> DraftPortDefinition:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        dp = await self._get_port_or_raise(draft_id, port_id)
        if "port_number" in payload:
            new_pn = int(payload["port_number"])
            if new_pn != dp.port_number:
                if any(p.port_number == new_pn and p.id != dp.id for p in draft.ports):
                    raise ValueError(f"端口 {new_pn} 已被其它行占用")
                dp.port_number = new_pn
        for attr in PORT_MUTABLE_ATTRS:
            if attr in payload:
                setattr(dp, attr, payload[attr])
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(dp)
        return dp

    async def delete_port(self, draft_id: int, port_id: int):
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        dp = await self._get_port_or_raise(draft_id, port_id)
        await self.db.delete(dp)
        draft.updated_at = datetime.utcnow()
        await self.db.commit()

    async def _get_port_or_raise(self, draft_id: int, port_id: int) -> DraftPortDefinition:
        res = await self.db.execute(
            select(DraftPortDefinition)
            .where(DraftPortDefinition.id == port_id)
            .where(DraftPortDefinition.draft_id == draft_id)
            .options(selectinload(DraftPortDefinition.fields))
        )
        dp = res.scalar_one_or_none()
        if not dp:
            raise ValueError(f"端口 {port_id} 不在草稿 {draft_id} 中")
        return dp

    # ───── 字段 CRUD ─────
    async def add_field(
        self, draft_id: int, port_id: int, payload: Dict[str, Any]
    ) -> DraftFieldDefinition:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        dp = await self._get_port_or_raise(draft_id, port_id)
        field_name = str(payload["field_name"]).strip()
        if any(f.field_name == field_name for f in dp.fields):
            raise ValueError(f"字段名 {field_name} 在端口 {dp.port_number} 已存在")
        df = DraftFieldDefinition(
            draft_port_id=port_id,
            field_name=field_name,
            field_offset=int(payload["field_offset"]),
            field_length=int(payload["field_length"]),
            data_type=payload.get("data_type", "bytes"),
            scale_factor=payload.get("scale_factor", 1.0),
            unit=payload.get("unit"),
            description=payload.get("description"),
            byte_order=payload.get("byte_order", "big"),
        )
        self.db.add(df)
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(df)
        return df

    async def update_field(
        self, draft_id: int, port_id: int, field_id: int, payload: Dict[str, Any]
    ) -> DraftFieldDefinition:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        dp = await self._get_port_or_raise(draft_id, port_id)
        field = next((f for f in dp.fields if f.id == field_id), None)
        if not field:
            raise ValueError(f"字段 {field_id} 不在端口 {port_id} 中")

        if "field_name" in payload:
            new_name = str(payload["field_name"]).strip()
            if new_name != field.field_name and any(
                f.field_name == new_name and f.id != field.id for f in dp.fields
            ):
                raise ValueError(f"字段名 {new_name} 已被占用")
            field.field_name = new_name
        for attr, caster in (
            ("field_offset", int),
            ("field_length", int),
            ("scale_factor", float),
        ):
            if attr in payload:
                setattr(field, attr, caster(payload[attr]))
        for attr in ("data_type", "unit", "description", "byte_order"):
            if attr in payload:
                setattr(field, attr, payload[attr])
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(field)
        return field

    async def delete_field(self, draft_id: int, port_id: int, field_id: int):
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        dp = await self._get_port_or_raise(draft_id, port_id)
        field = next((f for f in dp.fields if f.id == field_id), None)
        if not field:
            raise ValueError(f"字段 {field_id} 不在端口 {port_id} 中")
        await self.db.delete(field)
        draft.updated_at = datetime.utcnow()
        await self.db.commit()

    # ───── 批量端口 upsert ─────
    async def bulk_upsert_ports(
        self, draft_id: int, payload: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        draft = await self.get_draft(draft_id, with_fields=False)
        self._ensure_editable(draft)
        existing = {p.port_number: p for p in draft.ports}
        created = 0
        updated = 0
        for row in payload:
            if "port_number" not in row:
                continue
            pn = int(row["port_number"])
            if pn in existing:
                dp = existing[pn]
                for attr in PORT_MUTABLE_ATTRS:
                    if attr in row:
                        setattr(dp, attr, row[attr])
                updated += 1
            else:
                dp = DraftPortDefinition(
                    draft_id=draft.id,
                    port_number=pn,
                    **{attr: row.get(attr) for attr in PORT_MUTABLE_ATTRS},
                )
                self.db.add(dp)
                existing[pn] = dp
                created += 1
        draft.updated_at = datetime.utcnow()
        await self.db.commit()
        return {"created": created, "updated": updated}

    # ───── diff ─────
    async def compute_diff(self, draft_id: int) -> Dict[str, Any]:
        draft = await self.get_draft(draft_id, with_fields=True)
        if not draft.base_version_id:
            # 新架次 Draft：所有端口都是新增
            return {
                "ports_added": [self._port_snapshot(p) for p in draft.ports],
                "ports_removed": [],
                "ports_property_changed": [],
                "fields_added": [
                    {"port_number": p.port_number, **self._field_snapshot(f)}
                    for p in draft.ports for f in p.fields
                ],
                "fields_removed": [],
                "fields_changed": [],
            }

        pv_res = await self.db.execute(
            select(ProtocolVersion)
            .where(ProtocolVersion.id == draft.base_version_id)
            .options(
                selectinload(ProtocolVersion.ports).selectinload(PortDefinition.fields)
            )
        )
        pv = pv_res.scalar_one_or_none()
        if not pv:
            raise ValueError("基础版本已不存在，无法 diff")

        base_ports_by_num = {p.port_number: p for p in pv.ports}
        draft_ports_by_num = {p.port_number: p for p in draft.ports}

        ports_added = [
            self._port_snapshot(dp)
            for pn, dp in draft_ports_by_num.items()
            if pn not in base_ports_by_num
        ]
        ports_removed = [
            self._port_snapshot(bp, from_db=True)
            for pn, bp in base_ports_by_num.items()
            if pn not in draft_ports_by_num
        ]
        ports_property_changed: List[Dict[str, Any]] = []
        fields_added: List[Dict[str, Any]] = []
        fields_removed: List[Dict[str, Any]] = []
        fields_changed: List[Dict[str, Any]] = []

        for pn, dp in draft_ports_by_num.items():
            if pn not in base_ports_by_num:
                # 此端口整体新增；字段全部算 added
                for f in dp.fields:
                    fields_added.append({"port_number": pn, **self._field_snapshot(f)})
                continue
            bp = base_ports_by_num[pn]
            port_diff = self._port_property_diff(bp, dp)
            if port_diff:
                ports_property_changed.append({"port_number": pn, "changes": port_diff})

            base_fields = {f.field_name: f for f in bp.fields}
            draft_fields = {f.field_name: f for f in dp.fields}
            for fname, df in draft_fields.items():
                if fname not in base_fields:
                    fields_added.append({"port_number": pn, **self._field_snapshot(df)})
                else:
                    fd = self._field_property_diff(base_fields[fname], df)
                    if fd:
                        fields_changed.append(
                            {"port_number": pn, "field_name": fname, "changes": fd}
                        )
            for fname, bf in base_fields.items():
                if fname not in draft_fields:
                    fields_removed.append({"port_number": pn, **self._field_snapshot(bf)})

        return {
            "ports_added": ports_added,
            "ports_removed": ports_removed,
            "ports_property_changed": ports_property_changed,
            "fields_added": fields_added,
            "fields_removed": fields_removed,
            "fields_changed": fields_changed,
        }

    @staticmethod
    def _port_snapshot(p: Any, *, from_db: bool = False) -> Dict[str, Any]:
        snap = {
            "port_number": p.port_number,
            "data_direction": p.data_direction,
            "field_count": len(p.fields) if getattr(p, "fields", None) else 0,
        }
        for attr in PORT_MUTABLE_ATTRS:
            snap[attr] = getattr(p, attr, None)
        return snap

    @staticmethod
    def _field_snapshot(f: Any) -> Dict[str, Any]:
        return {
            "field_name": f.field_name,
            "field_offset": f.field_offset,
            "field_length": f.field_length,
            "data_type": f.data_type,
            "byte_order": f.byte_order,
            "scale_factor": f.scale_factor,
            "unit": f.unit,
        }

    @staticmethod
    def _port_property_diff(base: Any, draft: Any) -> Dict[str, Dict[str, Any]]:
        diffs: Dict[str, Dict[str, Any]] = {}
        for attr in PORT_MUTABLE_ATTRS:
            b = getattr(base, attr, None)
            d = getattr(draft, attr, None)
            if (b or None) != (d or None):
                diffs[attr] = {"old": b, "new": d}
        return diffs

    @staticmethod
    def _field_property_diff(base: Any, draft: Any) -> Dict[str, Dict[str, Any]]:
        diffs: Dict[str, Dict[str, Any]] = {}
        for attr in (
            "field_offset",
            "field_length",
            "data_type",
            "byte_order",
            "scale_factor",
            "unit",
            "description",
        ):
            b = getattr(base, attr, None)
            d = getattr(draft, attr, None)
            if (b or None) != (d or None):
                diffs[attr] = {"old": b, "new": d}
        return diffs

    # ───── 导出 Excel ─────
    # 每个方向的列顺序严格对齐 ICD 6.0.x 原表头。"消息名称" 列按方向使用不同原字面：
    #   - 上行/网络交互: "上网设备消息名称"
    #   - 下行: "待转换TSN设备消息名称"
    # 字段行（展开）追加 ICD 字段级原表头: 消息内数据集 / 消息内偏移 / 长度
    # 协议族 / 数据类型 / 字节序 等为平台解析扩展，放在末尾并用括号标注
    _UPLINK_ICD_HEADERS = [
        ("消息编号", "message_id"),
        ("上网设备消息名称", "message_name"),
        ("消息源设备名称", "source_device"),
        ("消息源端接口编号", "source_interface_id"),
        ("UDP端口", "port_number"),
        ("组播组IP", "multicast_ip"),
        ("DIU编号", "diu_id"),
        ("消息周期", "period_ms"),
        ("备注", "description"),
        ("PortID", "port_id_label"),
    ]
    _DOWNLINK_ICD_HEADERS = [
        ("消息编号", "message_id"),
        ("待转换TSN设备消息名称", "message_name"),
        ("待转换TSN源端", "source_device"),
        ("DataSet目的端设备名称", "target_device"),
        ("DataSet传递路径", "dataset_path"),
        ("DIU编号集合", "diu_id_set"),
        ("DIU消息接收形式", "diu_recv_mode"),
        ("TSN消息源端IP", "tsn_source_ip"),
        ("承接转换的DIU IP", "diu_ip"),
        ("UDP端口", "port_number"),
        ("组播组IP", "multicast_ip"),
        ("消息周期", "period_ms"),
        ("备注", "description"),
        ("数据实际路径", "data_real_path"),
        ("DIU编号", "diu_id"),
        ("最终接收端设备", "final_recv_device"),
    ]
    _NETWORK_ICD_HEADERS = [
        ("消息编号", "message_id"),
        ("上网设备消息名称", "message_name"),
        ("消息源设备名称", "source_device"),
        ("消息源端接口编号", "source_interface_id"),
        ("UDP端口", "port_number"),
        ("组播组IP", "multicast_ip"),
        ("DIU编号", "diu_id"),
        ("消息周期", "period_ms"),
        ("备注", "description"),
        ("PortID", "port_id_label"),
        ("消息目的设备", "target_device"),
    ]
    _FIELD_HEADERS = [
        ("消息内数据集", "field_name"),
        ("消息内偏移", "field_offset"),
        ("长度", "field_length"),
    ]
    # 非 ICD 原表头的平台扩展列
    _FIELD_EXT = [
        ("数据类型(平台扩展)", "data_type"),
        ("字节序(平台扩展)", "byte_order"),
        ("系数(平台扩展)", "scale_factor"),
        ("单位(平台扩展)", "unit"),
        ("字段说明(平台扩展)", "description"),
    ]

    def _sheet_rows_for_direction(
        self, ports: List[DraftPortDefinition], dir_key: str
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        headers_def = {
            "uplink": self._UPLINK_ICD_HEADERS,
            "downlink": self._DOWNLINK_ICD_HEADERS,
            "network": self._NETWORK_ICD_HEADERS,
        }.get(dir_key, self._NETWORK_ICD_HEADERS)

        port_header_titles = [t for t, _ in headers_def]
        field_header_titles = [t for t, _ in self._FIELD_HEADERS]
        field_ext_titles = [t for t, _ in self._FIELD_EXT]
        full_headers = port_header_titles + field_header_titles + ["协议族(平台扩展)"] + field_ext_titles

        rows: List[Dict[str, Any]] = []
        for p in sorted(ports, key=lambda x: (x.port_number, (x.message_name or ""))):
            port_header_vals = {title: getattr(p, attr, None) for title, attr in headers_def}
            fields = sorted(list(p.fields or []), key=lambda x: x.field_offset)
            if not fields:
                row = {h: None for h in full_headers}
                row.update(port_header_vals)
                row["协议族(平台扩展)"] = p.protocol_family
                rows.append(row)
                continue
            for idx, f in enumerate(fields):
                row = {h: None for h in full_headers}
                if idx == 0:
                    row.update(port_header_vals)
                    row["协议族(平台扩展)"] = p.protocol_family
                for title, attr in self._FIELD_HEADERS:
                    row[title] = getattr(f, attr, None)
                for title, attr in self._FIELD_EXT:
                    row[title] = getattr(f, attr, None)
                rows.append(row)
        return full_headers, rows

    async def export_excel(self, draft_id: int) -> Tuple[bytes, str]:
        draft = await self.get_draft(draft_id, with_fields=True)

        ports_by_dir: Dict[str, List[DraftPortDefinition]] = {
            "uplink": [], "downlink": [], "network": [],
        }
        for p in draft.ports or []:
            dk = (p.data_direction or "").lower() or "network"
            if dk not in ports_by_dir:
                dk = "network"
            ports_by_dir[dk].append(p)

        buf = io.BytesIO()
        sheet_labels = {"uplink": "上行数据", "downlink": "下行数据", "network": "网络交互数据"}
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for dir_key, label in sheet_labels.items():
                headers, rows = self._sheet_rows_for_direction(ports_by_dir.get(dir_key, []), dir_key)
                if rows:
                    pd.DataFrame(rows, columns=headers).to_excel(writer, sheet_name=label, index=False)
                else:
                    pd.DataFrame(columns=headers).to_excel(writer, sheet_name=label, index=False)
        buf.seek(0)
        safe = "".join(c for c in draft.name if c.isalnum() or c in ("-", "_"))[:40] or f"draft_{draft.id}"
        filename = f"{safe}_v{draft.target_version}.xlsx"
        return buf.getvalue(), filename


def serialize_port(p: DraftPortDefinition) -> Dict[str, Any]:
    from .protocol_service import resolve_port_family
    data = {
        "id": p.id,
        "port_number": p.port_number,
        "data_direction": p.data_direction,
        "protocol_family_resolved": resolve_port_family(
            p.port_number, db_family=p.protocol_family
        ),
        "field_count": len(p.fields) if getattr(p, "fields", None) else 0,
    }
    for attr in PORT_MUTABLE_ATTRS:
        data[attr] = getattr(p, attr, None)
    return data


def serialize_field(f: DraftFieldDefinition) -> Dict[str, Any]:
    return {
        "id": f.id,
        "field_name": f.field_name,
        "field_offset": f.field_offset,
        "field_length": f.field_length,
        "data_type": f.data_type,
        "scale_factor": f.scale_factor,
        "unit": f.unit,
        "description": f.description,
        "byte_order": f.byte_order,
    }


def serialize_draft(draft: ProtocolVersionDraft) -> Dict[str, Any]:
    return {
        "id": draft.id,
        "protocol_id": draft.protocol_id,
        "base_version_id": draft.base_version_id,
        "source_type": draft.source_type,
        "name": draft.name,
        "target_version": draft.target_version,
        "description": draft.description,
        "status": draft.status,
        "submit_note": draft.submit_note,
        "created_by": draft.created_by,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "source_file_path": draft.source_file_path,
        "published_version_id": draft.published_version_id,
        "port_count": len(draft.ports) if getattr(draft, "ports", None) else 0,
    }
