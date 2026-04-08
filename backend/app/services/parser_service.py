# -*- coding: utf-8 -*-
"""TSN数据包解析服务"""
import os
import struct
import asyncio
import time
import re
import math
import bisect
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.dataset as ds
import pyarrow.csv as pacsv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import DATA_DIR, UPLOAD_DIR
from ..models import ParseTask, ParseResult, PortDefinition, FieldDefinition, ParserProfile
from .protocol_service import ProtocolService
from .parsers import ParserRegistry, BaseParser, FieldLayout
from .fcc_context_service import build_fcc_irs_context

# ATG 端口：仅与 IRS 核对，不做 RTK 时间核对（ICD：8050/8052 对应 IRS 流）
ATG_IRS_ONLY_PORTS = frozenset({8050, 8052})
# ATG 端口：仅与 RTK 核对时间，不做 IRS（ICD：8051/8053 对应 RTK 流）
ATG_RTK_ONLY_PORTS = frozenset({8051, 8053})

# ATG(CPE): altitude_ft=英尺, ground_speed_kn=节 | IRS: altitude=米, 东/北速=m/s
# 8050/8052 核对衍生差：高度差在「英尺」上算 (ATG_ft − IRS_m×系数)；地速差在「节」上算 (ATG_kt − IRS_合成地速_m/s×系数)
_ATG_IRS_ALT_M_TO_FT = 3.280839895  # m → ft
_ATG_IRS_MPS_TO_KN = 1.943844492  # m/s → kt (1 kt = 0.514444… m/s)


def _atg_irs_angle_diff(atg_deg: float, irs_deg: float) -> float:
    """ATG 与 IRS 角度差值。

    ATG 航迹角值域 [-180, +180)，正=East of North（顺时针）。
    IRS 航向值域 [0, 360)，0=北，顺时针。
    先将 ATG 转换到 [0, 360) 统一值域，再取最短有向差 (-180, 180]。
    """
    atg_360 = float(atg_deg) % 360.0          # [-180,180) -> [0,360)
    irs_360 = float(irs_deg) % 360.0          # 保险：IRS 已经是 [0,360)
    d = (atg_360 - irs_360) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


class ParserService:
    """TSN数据包解析服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.protocol_service = ProtocolService(db)
        # 任务进度上报节流状态: {task_id: (last_commit_pct, last_commit_monotonic_ts)}
        self._progress_commit_state: Dict[int, Tuple[int, float]] = {}
    
    async def create_task(
        self,
        filename: str,
        file_path: str,
        device_parser_map: Dict[str, int] = None,
        protocol_version_id: int = None,
        selected_ports: List[int] = None,
        selected_devices: List[str] = None
    ) -> ParseTask:
        """创建解析任务
        
        仅新模式: device_parser_map = {"设备名": parser_profile_id, ...}
        """
        if not device_parser_map:
            raise ValueError("已禁用旧模式，create_task 必须提供 device_parser_map")
        task = ParseTask(
            filename=filename,
            file_path=file_path,
            device_parser_map=device_parser_map,
            protocol_version_id=protocol_version_id,
            selected_ports=selected_ports,
            selected_devices=selected_devices,
            status="pending"
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def get_task(self, task_id: int) -> Optional[ParseTask]:
        """获取任务"""
        result = await self.db.execute(
            select(ParseTask).where(ParseTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_atg_fcc_context(self, task_id: int) -> Optional[Dict[str, Any]]:
        """
        ATG 前置判定链路（解析侧）：
        - 从飞控状态帧(9001/9002/9003)判定主飞控
        - 从主飞控的飞控通道选择(9011/9012/9013)判定 IRS 通道
        """
        task = await self.get_task(task_id)
        if not task or not task.file_path:
            return None
        pcap_file = Path(task.file_path)
        if not pcap_file.is_file():
            return None
        return build_fcc_irs_context(str(pcap_file))

    @staticmethod
    def _resolve_irs_key_from_device_name(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        text = str(name)
        if "惯导1" in text or "IRS1" in text.upper() or "IRS 1" in text.upper():
            return "IRS1"
        if "惯导2" in text or "IRS2" in text.upper() or "IRS 2" in text.upper():
            return "IRS2"
        if "惯导3" in text or "IRS3" in text.upper() or "IRS 3" in text.upper():
            return "IRS3"
        m = re.search(r"([123])", text)
        if m:
            return f"IRS{m.group(1)}"
        return None

    def build_atg_check_column(
        self,
        atg_records: List[Dict[str, Any]],
        main_fcc_changes: List[Dict[str, Any]],
        irs_events: List[Dict[str, Any]],
        irs_data_by_key: Dict[str, List[Dict[str, Any]]],
        rtk_data: List[Dict[str, Any]],
        atg_port: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        \u4e3a ATG \u7ed3\u679c\u884c\u6784\u5efa\u201c\u6838\u5bf9\u201d\u5217\uff08\u4e8c\u5206\u67e5\u627e\uff0c\u5728\u89e3\u6790\u4fdd\u5b58\u524d\u4e00\u6b21\u6027\u8c03\u7528\uff09\u3002
        \u6240\u6709\u6570\u636e\u5747\u6765\u81ea\u5185\u5b58\u4e2d\u7684\u89e3\u6790\u7ed3\u679c\uff0c\u4e0d\u518d\u91cd\u65b0\u8bfb pcap\u3002
        8050/8052 \u9644\u52a0\u5dee\u503c\uff08\u4e0e\u7ecf\u7eac\u5ea6\u540c\u6bb5\u7528 \u201c| \u201d\u5206\u9694\uff09\uff1aATG \u9ad8\u5ea6 ft\u3001\u5730\u901f kt\uff1bIRS \u9ad8\u5ea6 m\u3001\u4e1c\u5317\u901f m/s\uff0c\u6362\u7b97\u540e\u4e0e ATG \u76f8\u51cf\u3002
        """
        if not atg_records:
            return atg_records

        irs_only = atg_port is not None and atg_port in ATG_IRS_ONLY_PORTS
        rtk_only = atg_port is not None and atg_port in ATG_RTK_ONLY_PORTS

        if rtk_only and not rtk_data:
            for r in atg_records:
                r["\u6838\u5bf9"] = "\u65e0RTK\u89e3\u6790\u6570\u636e"
            return atg_records

        if not rtk_only and not main_fcc_changes and not irs_events:
            for r in atg_records:
                r["\u6838\u5bf9"] = "\u65e0FCC\u4e0a\u4e0b\u6587"
            return atg_records

        if irs_only and not irs_data_by_key:
            for r in atg_records:
                r["\u6838\u5bf9"] = "\u65e0IRS\u89e3\u6790\u6570\u636e"
            return atg_records

        if not irs_only and not rtk_only and not irs_data_by_key and not rtk_data:
            for r in atg_records:
                r["\u6838\u5bf9"] = "\u65e0IRS/RTK\u89e3\u6790\u6570\u636e"
            return atg_records

        irs_ts_lists: Dict[str, List[float]] = {}
        for key, rows in irs_data_by_key.items():
            irs_ts_lists[key] = [r.get("timestamp", 0.0) for r in rows]
        rtk_ts_list = [r.get("timestamp", 0.0) for r in rtk_data] if rtk_data else []

        fcc_ts = [c.get("timestamp", 0.0) for c in main_fcc_changes]
        irs_ev_ts = [e.get("timestamp", 0.0) for e in irs_events]

        for row in atg_records:
            ts = row.get("timestamp")
            if ts is None:
                row["\u6838\u5bf9"] = "\u65e0\u65f6\u95f4\u6233"
                continue

            summary_parts: List[str] = []

            if not rtk_only:
                idx = bisect.bisect_right(fcc_ts, ts) - 1
                main_fcc = main_fcc_changes[idx].get("main_fcc") if idx >= 0 else None

                current_irs = None
                irs_idx = bisect.bisect_right(irs_ev_ts, ts) - 1
                while irs_idx >= 0:
                    e = irs_events[irs_idx]
                    if not main_fcc or e.get("main_fcc") == main_fcc:
                        current_irs = e.get("irs_name")
                        break
                    irs_idx -= 1

                lat = row.get("latitude_deg")
                lon = row.get("longitude_deg")
                if current_irs and current_irs in irs_data_by_key and lat is not None and lon is not None:
                    arr = irs_ts_lists[current_irs]
                    hi = bisect.bisect_right(arr, ts)
                    cands = []
                    for ci in range(max(0, hi - 2), hi):
                        if (ts - arr[ci]) <= 0.020:
                            cands.append(irs_data_by_key[current_irs][ci])
                    if len(cands) == 2 and all(("latitude" in c and "longitude" in c) for c in cands):
                        try:
                            irs_lat_avg = (float(cands[0]["latitude"]) + float(cands[1]["latitude"])) / 2.0
                            irs_lon_avg = (float(cands[0]["longitude"]) + float(cands[1]["longitude"])) / 2.0
                            d_lat = float(lat) - irs_lat_avg
                            d_lon = float(lon) - irs_lon_avg
                            summary_parts.append(f"{current_irs}\u5dee\u503c(lat={d_lat:.8f}, lon={d_lon:.8f})")
                            if irs_only:
                                try:
                                    extras: List[str] = []

                                    def _avg2(k: str) -> Optional[float]:
                                        v0 = cands[0].get(k)
                                        v1 = cands[1].get(k)
                                        if v0 is None or v1 is None:
                                            return None
                                        return (float(v0) + float(v1)) / 2.0

                                    atg_alt = row.get("altitude_ft")
                                    irs_alt_m = _avg2("altitude")
                                    if atg_alt is not None and irs_alt_m is not None:
                                        irs_alt_ft = irs_alt_m * _ATG_IRS_ALT_M_TO_FT
                                        extras.append(
                                            f"(\u9ad8\u5ea6 ft, ATG \u82f1\u5c3a-IRS\u7c73)={float(atg_alt) - irs_alt_ft:.4f}"
                                        )

                                    atg_trk = row.get("true_track_angle_deg")
                                    irs_hdg = _avg2("heading")
                                    if atg_trk is not None and irs_hdg is not None:
                                        trk_diff = _atg_irs_angle_diff(float(atg_trk), irs_hdg)
                                        extras.append(
                                            f"(\u822a\u8ff9-\u822a\u5411 \u00b0)={trk_diff:.4f}"
                                        )

                                    atg_gsp = row.get("ground_speed_kn")
                                    e0, e1 = cands[0].get("east_velocity"), cands[1].get("east_velocity")
                                    n0, n1 = cands[0].get("north_velocity"), cands[1].get("north_velocity")
                                    if (
                                        atg_gsp is not None
                                        and e0 is not None
                                        and e1 is not None
                                        and n0 is not None
                                        and n1 is not None
                                    ):
                                        irs_e_avg = (float(e0) + float(e1)) / 2.0
                                        irs_n_avg = (float(n0) + float(n1)) / 2.0
                                        irs_gs_mps = math.hypot(irs_e_avg, irs_n_avg)
                                        irs_gs_kn = irs_gs_mps * _ATG_IRS_MPS_TO_KN
                                        extras.append(
                                            f"(\u5730\u901f kn, ATG \u8282-IRS \u5408\u6210 m/s)={float(atg_gsp) - irs_gs_kn:.4f}"
                                        )

                                    atg_pitch = row.get("pitch_angle_deg")
                                    irs_pitch = _avg2("pitch")
                                    if atg_pitch is not None and irs_pitch is not None:
                                        extras.append(f"(\u4fef\u4ef0 \u00b0)={float(atg_pitch) - irs_pitch:.4f}")

                                    atg_roll = row.get("roll_angle_deg")
                                    irs_roll = _avg2("roll")
                                    if atg_roll is not None and irs_roll is not None:
                                        extras.append(f"(\u6eda\u8f6c \u00b0)={float(atg_roll) - irs_roll:.4f}")

                                    if extras:
                                        summary_parts.append(", ".join(extras))
                                except Exception:
                                    pass
                        except Exception:
                            summary_parts.append(f"{current_irs}\u5dee\u503c\u8ba1\u7b97\u5931\u8d25")
                    else:
                        summary_parts.append(f"{current_irs}\u524d2\u5305\u4e0d\u8db3(<20ms)")
                else:
                    summary_parts.append("IRS\u6761\u4ef6\u4e0d\u8db3")

            if not irs_only:
                atg_time = row.get("utc_time")
                if atg_time and rtk_ts_list:
                    hi = bisect.bisect_right(rtk_ts_list, ts)
                    rtk_cands = []
                    for ci in range(max(0, hi - 2), hi):
                        if (ts - rtk_ts_list[ci]) <= 0.400:
                            rtk_cands.append(rtk_data[ci])
                    if len(rtk_cands) == 2:
                        rtk_times = [str(r.get("utc_time") or "") for r in rtk_cands]
                        matched = any(t == str(atg_time) for t in rtk_times if t)
                        summary_parts.append(f"RTK\u65f6\u95f4{'\u5bf9\u5e94' if matched else '\u4e0d\u5bf9\u5e94'}")
                    else:
                        summary_parts.append("RTK\u524d2\u5305\u4e0d\u8db3(<400ms)")
                else:
                    summary_parts.append("RTK\u65f6\u95f4\u6761\u4ef6\u4e0d\u8db3")

            row["\u6838\u5bf9"] = " | ".join(summary_parts)

        return atg_records

    async def get_tasks(self, limit: int = 50, offset: int = 0) -> Tuple[List[ParseTask], int]:
        """获取任务列表"""
        from sqlalchemy import func
        count_result = await self.db.execute(select(func.count(ParseTask.id)))
        total = count_result.scalar()
        
        result = await self.db.execute(
            select(ParseTask)
            .order_by(ParseTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total
    
    async def update_task_status(
        self, 
        task_id: int, 
        status: str,
        total_packets: int = None,
        parsed_packets: int = None,
        error_message: str = None,
        progress: int = None,
    ):
        """更新任务状态"""
        task = await self.get_task(task_id)
        if task:
            task.status = status
            if total_packets is not None:
                task.total_packets = total_packets
            if parsed_packets is not None:
                task.parsed_packets = parsed_packets
            if error_message is not None:
                task.error_message = error_message
            if progress is not None:
                task.progress = min(100, max(0, int(progress)))
            if status == "completed":
                task.progress = 100
            elif status == "failed":
                task.progress = 0
            if status in ("completed", "failed"):
                task.completed_at = datetime.utcnow()
            await self.db.commit()

    @staticmethod
    def _cleanup_pcap(file_path: str) -> None:
        """解析完成/失败后删除原始 pcap 文件以释放磁盘空间"""
        if not file_path:
            return
        try:
            p = Path(file_path)
            shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
            try:
                # 平台共享库文件需要保留，不能在解析后删除
                if p.resolve().is_relative_to(shared_dir):
                    print(f"[Cleanup] 跳过共享文件: {p.name}")
                    return
            except Exception:
                pass
            if p.is_file():
                size_mb = p.stat().st_size / (1024 * 1024)
                p.unlink()
                print(f"[Cleanup] 已删除原始文件: {p.name} ({size_mb:.1f} MB)")
        except Exception as exc:
            print(f"[Cleanup] 删除失败: {file_path} -> {exc}")

    async def _report_file_read_progress(
        self,
        task_id: int,
        f,
        file_size: int,
        last_pct: List[int],
        pass_index: int = 0,
        total_passes: int = 1,
        parsed_so_far: int = None,
        last_parsed_committed: List[int] = None,
    ) -> None:
        """根据文件读取位置上报解析进度（0-99，完成时由 update_task_status 置 100）。
        
        parsed_so_far / last_parsed_committed: 可选，用于在解析过程中更新「已解析条数」，
        避免界面长期显示 0（parsed_packets 仅在完成时写入的旧行为）。
        """
        if task_id is None or file_size <= 0:
            return
        try:
            pos = f.tell()
        except OSError:
            return
        frac = min(max(pos / file_size, 0.0), 1.0)
        if total_passes > 1:
            pct = int(((pass_index + frac) / total_passes) * 100)
        else:
            pct = int(frac * 100)
        pct = min(pct, 99)
        if pct <= last_pct[0]:
            return
        last_pct[0] = pct

        # 双阈值节流：进度至少变化 3% 或距离上次写库超过 2 秒才 commit
        # 避免大文件解析期间高频事务提交导致 SQLite 锁竞争。
        now = time.monotonic()
        last_committed_pct, last_ts = self._progress_commit_state.get(task_id, (-1, 0.0))
        should_commit = (
            last_committed_pct < 0
            or pct >= 99
            or (pct - last_committed_pct) >= 3
            or (now - last_ts) >= 2.0
        )
        if should_commit:
            self._progress_commit_state[task_id] = (pct, now)
            parsed_arg = None
            if (
                parsed_so_far is not None
                and last_parsed_committed is not None
                and parsed_so_far != last_parsed_committed[0]
            ):
                parsed_arg = parsed_so_far
                last_parsed_committed[0] = parsed_so_far
            await self.update_task_status(
                task_id, "processing", progress=pct, parsed_packets=parsed_arg
            )
    
    async def get_parser_profile(self, profile_id: int) -> Optional[ParserProfile]:
        """获取解析版本配置"""
        result = await self.db.execute(
            select(ParserProfile).where(ParserProfile.id == profile_id)
        )
        return result.scalar_one_or_none()
    
    async def get_parser_profiles(self, active_only: bool = True) -> List[ParserProfile]:
        """获取所有解析版本配置"""
        query = select(ParserProfile)
        if active_only:
            query = query.where(ParserProfile.is_active == True)
        query = query.order_by(ParserProfile.name, ParserProfile.version)
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def _build_network_layout(
        self, protocol_version_id: int, target_ports: List[int]
    ) -> Dict[int, List[FieldLayout]]:
        """
        从TSN网络配置中构造字段布局。
        
        返回: {端口号: [FieldLayout, ...], ...}
        """
        network_layout: Dict[int, List[FieldLayout]] = {}
        
        ports = await self.protocol_service.get_ports_by_version(protocol_version_id)
        
        for port_def in ports:
            if port_def.port_number not in target_ports:
                continue
            
            fields = []
            for field_def in port_def.fields:
                fields.append(FieldLayout(
                    field_name=field_def.field_name,
                    field_offset=field_def.field_offset,
                    field_length=field_def.field_length,
                    data_type=field_def.data_type,
                    scale_factor=field_def.scale_factor,
                    unit=field_def.unit,
                    description=field_def.description,
                ))
            
            # 按偏移排序
            fields.sort(key=lambda f: f.field_offset)
            network_layout[port_def.port_number] = fields
        
        return network_layout
    
    async def parse_pcapng(self, task_id: int) -> bool:
        """
        解析pcapng文件
        
        新模式 (device_parser_map):
            按设备分配端口和解析器，每个解析器只扫描属于该设备的端口。
        """
        print(f"[Parser] 获取任务 {task_id}")
        task = await self.get_task(task_id)
        if not task:
            print(f"[Parser] 任务 {task_id} 不存在")
            return False
        
        print(f"[Parser] 任务文件: {task.file_path}")
        await self.update_task_status(task_id, "processing", progress=0)
        
        try:
            # 获取所有端口定义
            port_device_map: Dict[int, str] = {}
            if task.protocol_version_id:
                all_port_defs = await self.protocol_service.get_ports_by_version(task.protocol_version_id)
                for port in all_port_defs:
                    # 优先使用 source_device（发送端）作为设备归属
                    if port.source_device:
                        port_device_map[port.port_number] = port.source_device
                    elif port.message_name:
                        port_device_map[port.port_number] = port.message_name
                    elif port.description:
                        port_device_map[port.port_number] = port.description
            
            # 获取设备到端口映射
            device_port_map: Dict[str, List[int]] = {}
            if task.protocol_version_id:
                device_port_map = await self.protocol_service.get_device_port_mapping(task.protocol_version_id)
            
            # =============== 构建解析计划 ===============
            # 合并同一个 parser 的端口，避免重复读取文件
            # merged_plan: {pid: (parser_instance, set_of_ports, [labels])}
            merged_plan: Dict[int, tuple] = {}
            
            if not task.device_parser_map:
                await self.update_task_status(task_id, "failed", error_message="已禁用旧模式：任务缺少 device_parser_map")
                return False
            print(f"[Parser] 使用 device_parser_map 模式")
            for dev_name, pid in task.device_parser_map.items():
                pid = int(pid)
                dev_ports = device_port_map.get(dev_name, [])
                if not dev_ports:
                    print(f"[Parser]   设备 {dev_name}: 无对应端口，跳过")
                    continue
                
                if pid not in merged_plan:
                    profile = await self.get_parser_profile(pid)
                    if not profile:
                        print(f"[Parser]   警告: 解析器 {pid} 不存在，跳过设备 {dev_name}")
                        continue
                    parser = ParserRegistry.create(profile.parser_key)
                    if not parser:
                        print(f"[Parser]   警告: 解析器 {profile.parser_key} 未注册")
                        continue
                    merged_plan[pid] = (parser, set(), [], profile.name)
                
                merged_plan[pid][1].update(dev_ports)
                merged_plan[pid][2].append(dev_name)
                print(f"[Parser]   {dev_name} -> {merged_plan[pid][3]}: 端口 {sorted(dev_ports)}")
            
            if not merged_plan:
                await self.update_task_status(task_id, "failed", error_message="未能构建有效的解析计划")
                return False
            
            # 汇总所有需要解析的端口
            all_target_ports = set()
            for _, (_, ports, _, _) in merged_plan.items():
                all_target_ports.update(ports)
            
            target_ports_list = sorted(all_target_ports)
            print(f"[Parser] 目标端口({len(target_ports_list)}个): {target_ports_list}")
            
            # 构造网络配置布局
            network_layout: Dict[int, List[FieldLayout]] = {}
            if task.protocol_version_id and target_ports_list:
                print(f"[Parser] 从TSN网络配置(版本ID={task.protocol_version_id})加载字段布局...")
                network_layout = await self._build_network_layout(
                    task.protocol_version_id, target_ports_list
                )
            
            # =============== 单次遍历解析（所有解析器共享一次文件读取） ===============
            total_records = 0
            
            all_parsed_data = await self._parse_single_pass(
                task.file_path, merged_plan, network_layout, task_id=task_id
            )
            
            if not all_parsed_data:
                await self.update_task_status(task_id, "failed", error_message="未能解析出任何数据，请确认数据文件和解析器选择是否正确")
                return False
            
            await self.update_task_status(task_id, "processing", progress=95)

            # FCC 后处理：为每行 FCC 记录回填当前主飞控，同时构建 ATG 核对所需的事件列表
            fcc_pid = None
            for pid, (parser, _, _, _) in merged_plan.items():
                if pid in all_parsed_data:
                    profile_tmp = await self.get_parser_profile(pid)
                    if profile_tmp and (profile_tmp.protocol_family or "").lower() == "fcc":
                        fcc_pid = pid
                        break

            main_fcc_changes: List[Dict[str, Any]] = []
            irs_selection_events: List[Dict[str, Any]] = []

            if fcc_pid and fcc_pid in all_parsed_data:
                fcc_all_rows: List[Dict[str, Any]] = []
                for port_fcc, recs_fcc in all_parsed_data[fcc_pid].items():
                    fcc_all_rows.extend(recs_fcc)
                fcc_all_rows.sort(key=lambda x: x.get("timestamp", 0))

                current_main_fcc = None
                for row_fcc in fcc_all_rows:
                    ft = row_fcc.get("frame_type")
                    if ft == "fcc_status":
                        mf = row_fcc.get("main_fcc")
                        if mf and mf != current_main_fcc:
                            current_main_fcc = mf
                            main_fcc_changes.append({
                                "timestamp": row_fcc.get("timestamp", 0),
                                "main_fcc": mf,
                            })
                    elif ft == "fcc_channel_select":
                        src_fcc = row_fcc.get("source_fcc")
                        if current_main_fcc and src_fcc == current_main_fcc:
                            irs_selection_events.append({
                                "timestamp": row_fcc.get("timestamp", 0),
                                "main_fcc": current_main_fcc,
                                "irs_name": row_fcc.get("irs_channel_name"),
                            })
                    row_fcc["main_fcc"] = current_main_fcc

                print(f"[Parser] FCC 后处理: 回填 main_fcc 完成 ({len(fcc_all_rows)} 行), "
                      f"{len(main_fcc_changes)} 次主飞控变更, {len(irs_selection_events)} 次 IRS 通道事件")

            # ATG 核对列
            atg_pid = None
            for pid, (parser, _, _, _) in merged_plan.items():
                if parser.parser_key == "atg_cpe_v20260402" and pid in all_parsed_data:
                    atg_pid = pid
                    break
            if atg_pid is not None:
                irs_data_by_key: Dict[str, List[Dict[str, Any]]] = {}
                rtk_data_all: List[Dict[str, Any]] = []
                for pid2, (parser2, _, _, _) in merged_plan.items():
                    profile2 = await self.get_parser_profile(pid2)
                    family2 = (profile2.protocol_family or "").lower() if profile2 else ""
                    if family2 not in {"irs", "rtk"}:
                        continue
                    if pid2 not in all_parsed_data:
                        continue
                    for port2, recs2 in all_parsed_data[pid2].items():
                        if not recs2:
                            continue
                        sorted_recs = sorted(recs2, key=lambda x: x.get("timestamp", 0))
                        if family2 == "irs":
                            dev_name = port_device_map.get(port2)
                            irs_key = self._resolve_irs_key_from_device_name(dev_name)
                            if irs_key:
                                irs_data_by_key.setdefault(irs_key, []).extend(sorted_recs)
                        else:
                            rtk_data_all.extend(sorted_recs)
                for k in list(irs_data_by_key.keys()):
                    irs_data_by_key[k] = sorted(irs_data_by_key[k], key=lambda x: x.get("timestamp", 0))
                rtk_data_all = sorted(rtk_data_all, key=lambda x: x.get("timestamp", 0))

                for port_number, records in all_parsed_data[atg_pid].items():
                    if records:
                        print(f"[Parser] ATG 端口 {port_number}: 计算核对列 ({len(records)} 行)...")
                        self.build_atg_check_column(
                            records,
                            main_fcc_changes,
                            irs_selection_events,
                            irs_data_by_key,
                            rtk_data_all,
                            atg_port=port_number,
                        )
                print(f"[Parser] ATG 核对列计算完成")

            # 保存结果（进度 96% → 99%）
            save_items = [
                (pid, port_number, records)
                for pid, parsed_data in all_parsed_data.items()
                for port_number, records in parsed_data.items()
                if records
            ]
            save_total = len(save_items) or 1

            for save_idx, (pid, port_number, records) in enumerate(save_items):
                profile = await self.get_parser_profile(pid)
                profile_name = profile.name if profile else f"Parser-{pid}"
                parser_inst = merged_plan[pid][0] if pid in merged_plan else None

                result_file = await self._save_results(
                    task_id, port_number, records,
                    parser_id=pid, parser=parser_inst,
                )

                source_device = port_device_map.get(port_number)

                parse_result = ParseResult(
                    task_id=task_id,
                    port_number=port_number,
                    message_name=f"{profile_name} - Port {port_number}",
                    parser_profile_id=pid,
                    parser_profile_name=profile_name,
                    source_device=source_device,
                    record_count=len(records),
                    result_file=result_file,
                    time_start=datetime.fromtimestamp(records[0].get('timestamp', 0)) if records else None,
                    time_end=datetime.fromtimestamp(records[-1].get('timestamp', 0)) if records else None,
                )
                self.db.add(parse_result)
                total_records += len(records)

                save_pct = 96 + int((save_idx + 1) / save_total * 3)
                await self.update_task_status(task_id, "processing", progress=min(save_pct, 99))

            await self.db.commit()
            await self.update_task_status(task_id, "completed", parsed_packets=total_records)
            print(f"[Parser] 解析完成，共 {total_records} 条记录")
            self._cleanup_pcap(task.file_path)
            return True
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            await self.update_task_status(task_id, "failed", error_message=str(e))
            self._cleanup_pcap(task.file_path)
            return False
    
    async def _parse_with_custom_parser(
        self,
        file_path: str,
        parser: BaseParser,
        target_ports: Optional[List[int]],
        network_layout: Dict[int, List[FieldLayout]],
        task_id: Optional[int] = None,
        pass_index: int = 0,
        total_passes: int = 1,
    ) -> Dict[int, List[Dict]]:
        """使用自定义解析器解析pcapng文件
        
        Args:
            target_ports: 目标端口列表。
            task_id: 任务ID，用于上报解析进度
            pass_index/total_passes: 多遍扫描时用于合并进度百分比
        """
        print(f"[Parser] 使用自定义解析器: {parser.parser_key}")
        if target_ports is None:
            print("[Parser] 未提供目标端口，跳过解析")
            return {}
        parsed_data: Dict[int, List[Dict]] = {port: [] for port in target_ports}
        
        file_size = 0
        if task_id is not None and file_path:
            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                file_size = 0
        last_pct = [0]
        last_parsed_committed = [0]
        
        try:
            import dpkt
            print("[Parser] 使用dpkt解析...")
        except ImportError:
            print("[Parser] dpkt未安装")
            return {}
        
        try:
            packet_count = 0
            matched_count = 0
            target_set = set(target_ports)
            
            with open(file_path, 'rb') as f:
                try:
                    pcap = dpkt.pcapng.Reader(f)
                    print("[Parser] 使用pcapng格式读取")
                except Exception as e:
                    print(f"[Parser] pcapng格式失败: {e}, 尝试pcap格式")
                    f.seek(0)
                    try:
                        pcap = dpkt.pcap.Reader(f)
                        print("[Parser] 使用pcap格式读取")
                    except Exception as e2:
                        print(f"[Parser] pcap格式也失败: {e2}")
                        return {}
                
                use_reassembly = hasattr(parser, 'feed_packet')
                if use_reassembly:
                    print(f"[Parser] 使用拼包模式 (feed_packet)")
                    parser.reset_buffers()
                
                for timestamp, buf in pcap:
                    packet_count += 1
                    if packet_count % 50000 == 0:
                        print(f"[Parser]   进度: 已处理 {packet_count} 个包, 匹配 {matched_count} 个")
                        if task_id is not None:
                            await self._report_file_read_progress(
                                task_id,
                                f,
                                file_size,
                                last_pct,
                                pass_index,
                                total_passes,
                                parsed_so_far=matched_count,
                                last_parsed_committed=last_parsed_committed,
                            )
                    try:
                        eth = dpkt.ethernet.Ethernet(buf)
                        if isinstance(eth.data, dpkt.ip.IP):
                            ip = eth.data
                            if isinstance(ip.data, dpkt.udp.UDP):
                                udp = ip.data
                                dst_port = udp.dport
                                
                                if dst_port in target_set:
                                    payload = bytes(udp.data)
                                    if payload:
                                        port_layout = network_layout.get(dst_port)
                                        if use_reassembly:
                                            records = parser.feed_packet(
                                                payload, dst_port, timestamp, port_layout
                                            )
                                            for record in records:
                                                if dst_port not in parsed_data:
                                                    parsed_data[dst_port] = []
                                                parsed_data[dst_port].append(record)
                                                matched_count += 1
                                        else:
                                            record = parser.parse_packet(
                                                payload, dst_port, timestamp, port_layout
                                            )
                                            if record:
                                                if dst_port not in parsed_data:
                                                    parsed_data[dst_port] = []
                                                multi = record.pop("_multi_rows", None)
                                                if multi:
                                                    for r in multi:
                                                        r.pop("_multi_rows", None)
                                                        parsed_data[dst_port].append(r)
                                                        matched_count += 1
                                                else:
                                                    parsed_data[dst_port].append(record)
                                                    matched_count += 1
                    except Exception:
                        continue
                
                if use_reassembly:
                    for port in (target_set or parsed_data.keys()):
                        for record in parser.flush_buffer(port):
                            if port not in parsed_data:
                                parsed_data[port] = []
                            parsed_data[port].append(record)
                            matched_count += 1
            
            print(f"[Parser] 共读取 {packet_count} 个包，匹配 {matched_count} 个")
            
            for port, records in parsed_data.items():
                if records:
                    print(f"[Parser]   端口 {port}: {len(records)} 条记录")
            
            return parsed_data
            
        except Exception as e:
            print(f"[Parser] 解析错误: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    async def _parse_single_pass(
        self,
        file_path: str,
        merged_plan: Dict[int, tuple],
        network_layout: Dict[int, List[FieldLayout]],
        task_id: Optional[int] = None,
    ) -> Dict[int, Dict[int, List[Dict]]]:
        """单次遍历解析：所有解析器共享一次文件遍历，按端口分发到对应解析器。
        
        相比 _parse_with_custom_parser（每个解析器各遍历一次文件），
        此方法只读取文件一次，通过字节级预过滤快速跳过非目标包。
        
        Args:
            file_path: pcapng/pcap 文件路径
            merged_plan: {parser_id: (parser, ports_set, dev_labels, profile_name)}
            network_layout: {port: [FieldLayout, ...]}
            
        Returns:
            {parser_id: {port: [record_dict, ...]}}
        """
        try:
            import dpkt
        except ImportError:
            print("[Parser] dpkt未安装")
            return {}
        
        # 步骤A: 构建端口分发表 {port: (parser, pid, field_layout)}
        port_dispatch: Dict[int, tuple] = {}
        for pid, (parser, plan_ports, dev_labels, profile_name) in merged_plan.items():
            if plan_ports is None:
                continue
            for port in plan_ports:
                layout = network_layout.get(port)
                port_dispatch[port] = (parser, pid, layout)
        
        target_set = set(port_dispatch.keys())
        if not target_set:
            print("[Parser] 无目标端口，跳过解析")
            return {}
        
        print(f"[Parser] 单次遍历模式，目标端口({len(target_set)}个): {sorted(target_set)}")
        dispatched = {pid: set() for pid in merged_plan}
        for port, (_, pid, _) in port_dispatch.items():
            dispatched[pid].add(port)
        for pid, (_, _, dev_labels, profile_name) in merged_plan.items():
            if pid in dispatched:
                print(f"[Parser]   {profile_name} ({', '.join(dev_labels)}) -> 端口 {sorted(dispatched[pid])}")
        
        # 初始化结果容器
        all_parsed_data: Dict[int, Dict[int, List[Dict]]] = {}
        for pid, (_, plan_ports, _, _) in merged_plan.items():
            if plan_ports is None:
                continue
            all_parsed_data[pid] = {port: [] for port in plan_ports}
        
        # 检测哪些解析器支持拼包模式
        reassembly_parsers = set()
        for pid, (parser, _, _, profile_name) in merged_plan.items():
            if hasattr(parser, 'feed_packet'):
                reassembly_parsers.add(pid)
                parser.reset_buffers()
                print(f"[Parser]   {profile_name}: 使用拼包模式 (feed_packet)")
        
        packet_count = 0
        matched_count = 0
        skipped_by_prefilter = 0
        
        file_size = 0
        if task_id is not None and file_path:
            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                file_size = 0
        last_pct = [0]
        last_parsed_committed = [0]
        
        try:
            with open(file_path, 'rb') as f:
                try:
                    pcap = dpkt.pcapng.Reader(f)
                    print("[Parser] 使用pcapng格式读取")
                except Exception:
                    f.seek(0)
                    try:
                        pcap = dpkt.pcap.Reader(f)
                        print("[Parser] 使用pcap格式读取")
                    except Exception as e2:
                        print(f"[Parser] pcap格式也失败: {e2}")
                        return {}
                
                for timestamp, buf in pcap:
                    packet_count += 1
                    if packet_count % 50000 == 0:
                        print(f"[Parser]   进度: 已处理 {packet_count} 个包, "
                              f"匹配 {matched_count}, 预过滤跳过 {skipped_by_prefilter}")
                        if task_id is not None:
                            await self._report_file_read_progress(
                                task_id,
                                f,
                                file_size,
                                last_pct,
                                0,
                                1,
                                parsed_so_far=matched_count,
                                last_parsed_committed=last_parsed_committed,
                            )
                    
                    # --- 字节级预过滤：不构造对象，直接跳过非目标包 ---
                    if len(buf) >= 42 and buf[12] == 0x08 and buf[13] == 0x00 and buf[23] == 17:
                        dst_port_fast = (buf[36] << 8) | buf[37]
                        if dst_port_fast not in target_set:
                            skipped_by_prefilter += 1
                            continue
                    
                    # --- 匹配的包 或 非标准格式：走 dpkt 完整解析 ---
                    try:
                        eth = dpkt.ethernet.Ethernet(buf)
                        if not isinstance(eth.data, dpkt.ip.IP):
                            continue
                        ip = eth.data
                        if not isinstance(ip.data, dpkt.udp.UDP):
                            continue
                        udp = ip.data
                        dst_port = udp.dport
                        
                        if dst_port not in target_set:
                            continue
                        
                        payload = bytes(udp.data)
                        if not payload:
                            continue
                        
                        parser, pid, layout = port_dispatch[dst_port]
                        if pid in reassembly_parsers:
                            records = parser.feed_packet(payload, dst_port, timestamp, layout)
                            for record in records:
                                all_parsed_data[pid][dst_port].append(record)
                                matched_count += 1
                        else:
                            record = parser.parse_packet(payload, dst_port, timestamp, layout)
                            if record:
                                multi = record.pop("_multi_rows", None)
                                if multi:
                                    for r in multi:
                                        r.pop("_multi_rows", None)
                                        all_parsed_data[pid][dst_port].append(r)
                                        matched_count += 1
                                else:
                                    all_parsed_data[pid][dst_port].append(record)
                                    matched_count += 1
                    except Exception:
                        continue
                
                # 拼包解析器：刷新缓冲区提取剩余帧
                for pid in reassembly_parsers:
                    parser_obj = merged_plan[pid][0]
                    plan_ports = merged_plan[pid][1]
                    if plan_ports:
                        for port in plan_ports:
                            for record in parser_obj.flush_buffer(port):
                                all_parsed_data[pid][port].append(record)
                                matched_count += 1
            
            print(f"[Parser] 单次遍历完成: 共 {packet_count} 包, "
                  f"匹配 {matched_count}, 预过滤跳过 {skipped_by_prefilter}")
            
            for pid, port_data in all_parsed_data.items():
                for port, records in port_data.items():
                    if records:
                        print(f"[Parser]   解析器{pid} 端口{port}: {len(records)} 条记录")
            
            # 清理空端口
            result = {}
            for pid, port_data in all_parsed_data.items():
                cleaned = {p: recs for p, recs in port_data.items() if recs}
                if cleaned:
                    result[pid] = cleaned
            
            return result
            
        except Exception as e:
            print(f"[Parser] 单次遍历解析错误: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    async def _save_results(
        self,
        task_id: int,
        port_number: int,
        records: List[Dict],
        parser_id: int = None,
        parser: Any = None,
    ) -> str:
        """保存解析结果为Parquet文件，按端口裁剪列。

        如果 parser 提供了 get_output_columns(port)，则只保留该端口
        对应的列，去除其它 CAN 帧/消息类型产生的多余列。
        使用 pyarrow 直接写入以减少大表场景的内存和 CPU 开销。
        """
        result_dir = DATA_DIR / "results" / str(task_id)
        result_dir.mkdir(parents=True, exist_ok=True)

        if parser_id:
            result_file = result_dir / f"port_{port_number}_parser_{parser_id}.parquet"
        else:
            result_file = result_dir / f"port_{port_number}.parquet"

        # 确定需要保留的列
        target_cols = None
        if parser is not None and hasattr(parser, "get_output_columns"):
            try:
                target_cols = parser.get_output_columns(port_number)
            except Exception:
                target_cols = None

        if target_cols:
            trimmed = [{k: r.get(k) for k in target_cols} for r in records]
        else:
            trimmed = records

        print(f"[Parser] 保存端口 {port_number}: {len(trimmed)} 行"
              + (f", {len(target_cols)} 列" if target_cols else ""))
        table = pa.Table.from_pylist(trimmed)
        if "BeijingDateTime" in table.schema.names:
            idx = table.schema.get_field_index("BeijingDateTime")
            table = table.set_column(
                idx, pa.field("BeijingDateTime", pa.string()),
                table.column("BeijingDateTime").cast(pa.string()),
            )
        pq.write_table(table, str(result_file))

        return str(result_file)
    
    def _find_parquet_file(self, result_dir: Path, port_number: int, parser_id: int = None) -> Optional[Path]:
        """查找 parquet 结果文件，兼容新旧命名格式"""
        if parser_id:
            f = result_dir / f"port_{port_number}_parser_{parser_id}.parquet"
            if f.exists():
                return f
        # 回退到不带 parser_id 的旧格式
        f = result_dir / f"port_{port_number}.parquet"
        if f.exists():
            return f
        # 尝试搜索该端口的任意 parser 文件
        if not parser_id:
            for candidate in result_dir.glob(f"port_{port_number}_parser_*.parquet"):
                return candidate
        return None
    
    async def get_results(self, task_id: int) -> List[ParseResult]:
        """获取任务的解析结果"""
        result = await self.db.execute(
            select(ParseResult).where(ParseResult.task_id == task_id)
        )
        return result.scalars().all()

    @staticmethod
    def _keep_datetime_as_str(df: pd.DataFrame) -> pd.DataFrame:
        """防止 pandas 把 BeijingDateTime 等时间字符串列自动推断为 datetime64，
        确保导出 CSV/Excel 时毫秒精度不丢失。"""
        for col in ("BeijingDateTime",):
            if col in df.columns and hasattr(df[col], "dt"):
                df[col] = df[col].astype(str)
        return df

    def _build_time_filter(
        self,
        schema_names: List[str],
        time_start: float = None,
        time_end: float = None,
    ):
        """构建 pyarrow dataset 过滤表达式"""
        if "timestamp" not in schema_names:
            return None
        filt = None
        if time_start is not None:
            filt = ds.field("timestamp") >= time_start
        if time_end is not None:
            right = ds.field("timestamp") <= time_end
            filt = right if filt is None else (filt & right)
        return filt

    def _iter_filtered_batches(
        self,
        result_file: Path,
        columns: Optional[List[str]] = None,
        time_start: float = None,
        time_end: float = None,
    ):
        """按批读取 Parquet，避免全量载入内存"""
        dataset = ds.dataset(str(result_file), format="parquet")
        schema_names = dataset.schema.names
        filt = self._build_time_filter(schema_names, time_start, time_end)
        scanner = dataset.scanner(
            columns=columns,
            filter=filt,
            batch_size=65536,
        )
        return scanner.to_batches(), schema_names
    
    async def get_result_data(
        self,
        task_id: int,
        port_number: int,
        page: int = 1,
        page_size: int = 100,
        time_start: float = None,
        time_end: float = None,
        parser_id: int = None
    ) -> Tuple[List[Dict], int, List[str]]:
        """获取解析结果数据
        
        Args:
            task_id: 任务ID
            port_number: 端口号
            page: 页码
            page_size: 每页大小
            time_start: 开始时间戳
            time_end: 结束时间戳
            parser_id: 解析器ID (可选, 多解析器时用于区分)
        """
        result_dir = DATA_DIR / "results" / str(task_id)
        
        result_file = self._find_parquet_file(result_dir, port_number, parser_id)
        if not result_file:
            return [], 0, []
        
        start = (page - 1) * page_size
        end = start + page_size
        total = 0
        page_records: List[Dict[str, Any]] = []

        batches, schema_names = self._iter_filtered_batches(
            result_file, columns=None, time_start=time_start, time_end=time_end
        )
        for batch in batches:
            batch_rows = batch.num_rows
            if batch_rows <= 0:
                continue
            next_total = total + batch_rows
            if next_total > start and total < end:
                local_start = max(0, start - total)
                local_end = min(batch_rows, end - total)
                sliced = batch.slice(local_start, local_end - local_start)
                page_records.extend(sliced.to_pylist())
            total = next_total

        return page_records, total, schema_names
    
    async def get_time_series(
        self,
        task_id: int,
        port_number: int,
        field_name: str,
        time_start: float = None,
        time_end: float = None,
        max_points: int = 1000,
        parser_id: int = None
    ) -> Tuple[List[float], List[Any], Optional[List[str]]]:
        """获取时序数据，若存在对应 _enum 列则一并返回。

        Returns:
            (timestamps, values, enum_labels)
            enum_labels 为 None 表示该字段无枚举映射。
        """
        result_dir = DATA_DIR / "results" / str(task_id)
        
        result_file = self._find_parquet_file(result_dir, port_number, parser_id)
        if not result_file:
            return [], [], None
        
        _, schema_names = self._iter_filtered_batches(
            result_file, columns=None, time_start=None, time_end=None
        )
        if field_name not in schema_names or "timestamp" not in schema_names:
            return [], [], None

        enum_col = f"{field_name}_enum"
        has_enum = enum_col in schema_names
        fetch_cols = ["timestamp", field_name] + ([enum_col] if has_enum else [])

        # 第一遍：统计过滤后的总行数，不把整表放进内存
        total_rows = 0
        count_batches, _ = self._iter_filtered_batches(
            result_file, columns=["timestamp"], time_start=time_start, time_end=time_end
        )
        for b in count_batches:
            total_rows += b.num_rows
        if total_rows <= 0:
            return [], [], None

        # 第二遍：按目标采样点抽取
        fetch_batches, _ = self._iter_filtered_batches(
            result_file, columns=fetch_cols, time_start=time_start, time_end=time_end
        )

        timestamps: List[float] = []
        values: List[Any] = []
        enum_labels: List[str] = [] if has_enum else None

        if total_rows <= max_points:
            for b in fetch_batches:
                if b.num_rows <= 0:
                    continue
                timestamps.extend(b.column("timestamp").to_pylist())
                values.extend(b.column(field_name).to_pylist())
                if has_enum:
                    enum_labels.extend(b.column(enum_col).to_pylist())
            return timestamps, values, enum_labels

        pick_count = max(1, max_points)
        step = total_rows / pick_count
        target_indices = sorted({min(total_rows - 1, int(i * step)) for i in range(pick_count)})
        pointer = 0
        global_idx = 0

        for b in fetch_batches:
            rows = b.num_rows
            if rows <= 0 or pointer >= len(target_indices):
                global_idx += rows
                continue
            batch_start = global_idx
            batch_end = batch_start + rows
            local_positions: List[int] = []
            while pointer < len(target_indices) and target_indices[pointer] < batch_end:
                if target_indices[pointer] >= batch_start:
                    local_positions.append(target_indices[pointer] - batch_start)
                pointer += 1
            if local_positions:
                idx_array = pa.array(local_positions, type=pa.int32())
                picked = b.take(idx_array)
                timestamps.extend(picked.column("timestamp").to_pylist())
                values.extend(picked.column(field_name).to_pylist())
                if has_enum:
                    enum_labels.extend(picked.column(enum_col).to_pylist())
            global_idx = batch_end

        return timestamps, values, enum_labels
    
    async def export_data(
        self,
        task_id: int,
        port_number: int,
        format: str = "csv",
        time_start: float = None,
        time_end: float = None,
        parser_id: int = None,
        include_text_columns: bool = True,
    ) -> Optional[str]:
        """导出数据
        
        Args:
            task_id: 任务ID
            port_number: 端口号
            format: 导出格式
            time_start: 开始时间戳
            time_end: 结束时间戳
            parser_id: 解析器ID (可选, 多解析器时用于区分)
            include_text_columns: 是否导出文字列（字符串列）
        """
        result_dir = DATA_DIR / "results" / str(task_id)
        
        result_file = self._find_parquet_file(result_dir, port_number, parser_id)
        if not result_file:
            return None
        
        export_dir = DATA_DIR / "exports" / str(task_id)
        export_dir.mkdir(parents=True, exist_ok=True)
        
        # 导出文件名包含解析器ID
        suffix = f"_parser_{parser_id}" if parser_id else ""

        def _rename_export_time_col(names: List[str]) -> List[str]:
            return ["time" if n == "timestamp" else n for n in names]

        def _rename_batch_timestamp(b: pa.RecordBatch) -> pa.RecordBatch:
            new_names = _rename_export_time_col(list(b.schema.names))
            return pa.RecordBatch.from_arrays(
                [b.column(i) for i in range(b.num_columns)],
                names=new_names,
            )

        def _is_cn_description_col(name: str) -> bool:
            if name == "unit_id_cn":
                return True
            if name.endswith("_cn"):
                return True
            if name.endswith("_enum"):
                return True
            if name.endswith(".ssm_enum"):
                return True
            if name.endswith(".parity"):
                return True
            return False

        dataset = ds.dataset(str(result_file), format="parquet")
        source_schema = dataset.schema
        selected_columns: Optional[List[str]] = None
        if not include_text_columns:
            selected_columns = [
                f.name for f in source_schema
                if not _is_cn_description_col(f.name)
            ]
        
        batches, schema_names = self._iter_filtered_batches(
            result_file, columns=selected_columns, time_start=time_start, time_end=time_end
        )
        export_schema_names = selected_columns if selected_columns is not None else schema_names

        if format == "csv":
            export_file = export_dir / f"port_{port_number}{suffix}.csv"
            writer = None
            wrote_rows = False
            with open(export_file, "wb") as sink:
                sink.write(b"\xef\xbb\xbf")
                for b in batches:
                    renamed = _rename_batch_timestamp(b)
                    if writer is None:
                        writer = pacsv.CSVWriter(sink, renamed.schema)
                    writer.write_batch(renamed)
                    wrote_rows = wrote_rows or renamed.num_rows > 0
                if writer is not None:
                    writer.close()
            if not wrote_rows:
                pd.DataFrame(columns=_rename_export_time_col(export_schema_names)).to_csv(
                    export_file, index=False, encoding="utf-8-sig"
                )
        elif format == "excel":
            export_file = export_dir / f"port_{port_number}{suffix}.xlsx"
            table = dataset.scanner(
                columns=selected_columns,
                filter=self._build_time_filter(schema_names, time_start, time_end),
                batch_size=65536,
            ).to_table()
            df = table.to_pandas()
            self._keep_datetime_as_str(df)
            df.rename(columns={"timestamp": "time"}, inplace=True)
            df.to_excel(export_file, index=False)
        elif format == "parquet":
            export_file = export_dir / f"port_{port_number}{suffix}.parquet"
            writer = None
            wrote_rows = False
            for b in batches:
                renamed = _rename_batch_timestamp(b)
                if writer is None:
                    writer = pq.ParquetWriter(str(export_file), renamed.schema)
                writer.write_batch(renamed)
                wrote_rows = wrote_rows or renamed.num_rows > 0
            if writer is not None:
                writer.close()
            elif not wrote_rows:
                if selected_columns is None:
                    empty_arrays = [pa.array([], type=f.type) for f in source_schema]
                else:
                    typed_map = {f.name: f.type for f in source_schema}
                    empty_arrays = [pa.array([], type=typed_map[name]) for name in selected_columns]
                empty_table = pa.Table.from_arrays(
                    empty_arrays,
                    names=_rename_export_time_col(export_schema_names),
                )
                pq.write_table(empty_table, str(export_file))
        else:
            return None
        
        return str(export_file)
