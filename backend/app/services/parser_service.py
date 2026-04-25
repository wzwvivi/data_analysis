# -*- coding: utf-8 -*-
"""TSN数据包解析服务"""
import os
import time
import re
import math
import bisect
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.dataset as ds
import pyarrow.csv as pacsv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, String


class TaskCancelled(Exception):
    """Raised from inside the parse loop when the task was user-cancelled."""
from ..config import DATA_DIR, UPLOAD_DIR
from ..models import ParseTask, ParseResult, ParserProfile
from .protocol_service import ProtocolService
from .parsers import ParserRegistry, BaseParser, FieldLayout
from .fcc_context_service import build_fcc_irs_context
from .bundle import BundleNotFoundError, load_bundle
from .device_bundle import try_load_device_bundle
from .bundle import generator as bundle_generator

# 仅这批 family 走 version(bundle) 绑定；其余 family 继续使用 legacy ParserProfile 路径
VERSION_BOUND_FAMILIES = frozenset({"adc", "ra", "turn", "brake", "lgcu"})

# ATG 端口：仅与 IRS 核对，不做 RTK 时间核对（ICD：8050/8052 对应 IRS 流）
ATG_IRS_ONLY_PORTS = frozenset({8050, 8052})
# ATG 端口：仅与 RTK 核对时间，不做 IRS（ICD：8051/8053 对应 RTK 流）
ATG_RTK_ONLY_PORTS = frozenset({8051, 8053})

# ATG(CPE): altitude_ft=英尺, ground_speed_kn=节 | IRS: altitude=米, 东/北速=m/s
# 8050/8052 核对衍生差：高度差在「英尺」上算 (ATG_ft − IRS_m×系数)；地速差在「节」上算 (ATG_kt − IRS_合成地速_m/s×系数)
_ATG_IRS_ALT_M_TO_FT = 3.280839895  # m → ft
_ATG_IRS_MPS_TO_KN = 1.943844492  # m/s → kt (1 kt = 0.514444… m/s)

# 单端口记录数超过此阈值时溢出到临时 Parquet，降低峰值内存
_SPILL_THRESHOLD = int(os.environ.get("PARSE_SPILL_THRESHOLD", "50000"))


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
        selected_devices: List[str] = None,
        device_protocol_version_map: Optional[Dict[str, int]] = None,
    ) -> ParseTask:
        """创建解析任务（Phase 7：主路径走 device_protocol_version_map）。

        - ``device_protocol_version_map``：``{parser_family: device_protocol_version_id}``，
          新前端应只传这个字段。parser_service 会按 version.parser_key 实例化 parser。
        - ``device_parser_map``：``{device_name: parser_profile_id}``，老字段。
          为了让旧版前端、以及老任务"重新解析"仍然可用，这里保留读入，
          但至少要有两者之一，否则直接拒绝建任务。
        """
        if not device_parser_map and not device_protocol_version_map:
            raise ValueError(
                "create_task 必须提供 device_protocol_version_map 或 device_parser_map"
            )
        task = ParseTask(
            filename=filename,
            file_path=file_path,
            device_parser_map=device_parser_map or None,
            protocol_version_id=protocol_version_id,
            selected_ports=selected_ports,
            selected_devices=selected_devices,
            status="pending",
            device_protocol_version_map=device_protocol_version_map or None,
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

    async def get_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        q: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        protocol_version_id: Optional[int] = None,
        source: Optional[str] = None,  # 'local' / 'shared' / None
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        tag: Optional[str] = None,
        device: Optional[str] = None,
    ) -> Tuple[List[ParseTask], int]:
        """获取任务列表，支持任务中心所需的多维过滤。"""
        from sqlalchemy import func, or_

        base = select(ParseTask)

        if q:
            pattern = f"%{q.strip()}%"
            base = base.where(or_(
                ParseTask.filename.like(pattern),
                ParseTask.display_name.like(pattern),
            ))

        if statuses:
            base = base.where(ParseTask.status.in_(statuses))

        if protocol_version_id is not None:
            base = base.where(ParseTask.protocol_version_id == protocol_version_id)

        if source in ("local", "shared"):
            shared_dir = (UPLOAD_DIR / "shared_tsn").resolve().as_posix()
            pattern = f"{shared_dir}%"
            if source == "shared":
                base = base.where(ParseTask.file_path.like(pattern))
            else:
                base = base.where(~ParseTask.file_path.like(pattern))

        if date_from is not None:
            base = base.where(ParseTask.created_at >= date_from)
        if date_to is not None:
            base = base.where(ParseTask.created_at <= date_to)

        if tag:
            # 简单 LIKE 过滤 JSON 字段（SQLite 不能高效地 json_each，所以走 LIKE）
            tag_pattern = f'%"{tag}"%'
            base = base.where(ParseTask.tags.isnot(None)).where(
                func.cast(ParseTask.tags, String).like(tag_pattern)
            )

        if device:
            # 对 device_parser_map（JSON，形如 {"FCC1": 123, "大气数据系统": 456}）做键名模糊匹配
            dev_pattern = f'%"{device.strip()}%'
            base = base.where(ParseTask.device_parser_map.isnot(None)).where(
                func.cast(ParseTask.device_parser_map, String).like(dev_pattern)
            )

        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = int(count_result.scalar() or 0)

        result = await self.db.execute(
            base.order_by(ParseTask.created_at.desc())
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
        stage: Optional[str] = None,
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
            if stage is not None:
                task.stage = stage
            if status == "completed":
                task.progress = 100
            elif status in ("failed", "cancelled"):
                task.progress = 0
            if status == "processing" and task.started_at is None:
                task.started_at = datetime.utcnow()
            if status in ("completed", "failed", "cancelled"):
                task.completed_at = datetime.utcnow()
            await self.db.commit()

    async def request_cancel(self, task_id: int) -> bool:
        """请求取消任务：仅标记 cancel_requested，由解析循环协作退出。"""
        task = await self.get_task(task_id)
        if not task:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return False
        task.cancel_requested = 1
        if task.status == "pending":
            # 尚未进入解析的任务可以立刻置为 cancelled
            task.status = "cancelled"
            task.completed_at = datetime.utcnow()
            task.progress = 0
        await self.db.commit()
        return True

    async def is_cancel_requested(self, task_id: int) -> bool:
        from sqlalchemy import select as _select
        r = await self.db.execute(
            _select(ParseTask.cancel_requested).where(ParseTask.id == task_id)
        )
        val = r.scalar_one_or_none()
        return bool(val)

    async def sweep_orphan_tasks(self) -> int:
        """后端启动时调用：把所有残留在 pending/processing 状态的任务标记为 failed。

        FastAPI 进程 + ProcessPoolExecutor 都在容器内，容器重启或进程被杀后，
        所有解析 future 都会丢失。原本写在 DB 里的 ``processing`` 记录没人再去
        推进状态，就会永远卡在"取消中"/"解析中"。启动时一次性清扫，避免 UI
        出现僵尸任务。
        """
        from sqlalchemy import select as _select
        r = await self.db.execute(
            _select(ParseTask).where(ParseTask.status.in_(["pending", "processing"]))
        )
        tasks = r.scalars().all()
        now = datetime.utcnow()
        for t in tasks:
            reason = "后端重启时任务被中断" if not t.cancel_requested else "用户已请求取消，任务被后端重启中断"
            t.status = "failed"
            t.error_message = reason
            t.progress = 0
            t.stage = None
            t.completed_at = now
            if not t.started_at:
                t.started_at = now
        if tasks:
            await self.db.commit()
            print(f"[Parser] 启动清扫：{len(tasks)} 个僵尸解析任务被标记为 failed: "
                  f"{[t.id for t in tasks]}")
        return len(tasks)

    async def update_task_meta(
        self,
        task_id: int,
        *,
        display_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[ParseTask]:
        """重命名 / 打标签。参数为 None 代表不修改。"""
        task = await self.get_task(task_id)
        if not task:
            return None
        if display_name is not None:
            display_name = display_name.strip()
            task.display_name = display_name or None
        if tags is not None:
            cleaned = sorted({t.strip() for t in tags if t and t.strip()})
            task.tags = cleaned or None
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def delete_task(self, task_id: int, *, delete_pcap: bool = True) -> bool:
        """删除单个任务及其解析结果与原始文件。"""
        task = await self.get_task(task_id)
        if not task:
            return False
        file_path = task.file_path
        # 删结果目录
        try:
            result_dir = DATA_DIR / "results" / str(task_id)
            if result_dir.is_dir():
                import shutil as _shutil
                _shutil.rmtree(result_dir, ignore_errors=True)
        except Exception as exc:
            print(f"[DeleteTask] 清理结果目录失败 task={task_id}: {exc}")
        # 删相关 ParseResult 行
        from sqlalchemy import delete as _delete
        await self.db.execute(_delete(ParseResult).where(ParseResult.task_id == task_id))
        await self.db.execute(_delete(ParseTask).where(ParseTask.id == task_id))
        await self.db.commit()
        if delete_pcap and file_path:
            await self._cleanup_pcap_if_orphan(file_path)
        return True

    async def bulk_delete_tasks(self, task_ids: List[int]) -> int:
        """批量删除任务，返回删除成功条数。"""
        ok = 0
        for tid in task_ids:
            try:
                if await self.delete_task(int(tid)):
                    ok += 1
            except Exception as exc:
                print(f"[BulkDeleteTask] 删除 {tid} 失败: {exc}")
        return ok

    async def _cleanup_pcap_if_orphan(self, file_path: str) -> None:
        """仅当文件不再被任何任务/共享库引用时才删除。"""
        if not file_path:
            return
        try:
            p = Path(file_path)
            shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
            try:
                if p.resolve().is_relative_to(shared_dir):
                    print(f"[Cleanup] 保留共享文件: {p.name}")
                    return
            except Exception:
                pass
            # 若还有其他任务引用同一个路径，则保留
            from sqlalchemy import select as _select, func as _func
            cnt_r = await self.db.execute(
                _select(_func.count()).select_from(ParseTask).where(ParseTask.file_path == file_path)
            )
            cnt = int(cnt_r.scalar_one() or 0)
            if cnt > 0:
                print(f"[Cleanup] 仍被 {cnt} 个任务引用，保留: {p.name}")
                return
            if p.is_file():
                size_mb = p.stat().st_size / (1024 * 1024)
                p.unlink()
                print(f"[Cleanup] 已删除原始文件: {p.name} ({size_mb:.1f} MB)")
        except Exception as exc:
            print(f"[Cleanup] 删除失败: {file_path} -> {exc}")

    # 兼容旧代码：保留同名方法，但改为"只在孤立时清理"——不再解析后强删。
    @staticmethod
    def _cleanup_pcap(file_path: str) -> None:
        """兼容入口：解析成功不再删除用户原始文件，方便后续重新解析。"""
        # 保留签名但默认不做任何事，真正的清理发生在任务被显式删除时。
        return None

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
                task_id, "processing", progress=pct, parsed_packets=parsed_arg,
                stage="reading",
            )
            # 借助进度提交的节流点，顺带巡检一次「是否被用户取消」。
            if await self.is_cancel_requested(task_id):
                raise TaskCancelled(f"task {task_id} cancelled by user")
    
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
        从 TSN 网络协议中构造字段布局。
        
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
        if await self.is_cancel_requested(task_id):
            await self.update_task_status(task_id, "cancelled", progress=0, stage=None)
            return False
        await self.update_task_status(task_id, "processing", progress=0, stage="reading")
        
        try:
            # MR4: 加载 Bundle（严格锁 ParseTask.protocol_version_id，缺失尝试即时生成）
            runtime_bundle = None
            if task.protocol_version_id:
                try:
                    runtime_bundle = load_bundle(task.protocol_version_id)
                    print(
                        f"[Parser] 已加载 Bundle v{task.protocol_version_id}"
                        f" (schema={runtime_bundle.schema_version}, "
                        f"ports={len(runtime_bundle.ports)})"
                    )
                except BundleNotFoundError:
                    try:
                        await bundle_generator.generate_bundle(self.db, task.protocol_version_id)
                        runtime_bundle = load_bundle(task.protocol_version_id)
                        print(f"[Parser] Bundle v{task.protocol_version_id} 已按需补生成")
                    except Exception as exc:
                        print(f"[Parser] Bundle v{task.protocol_version_id} 无法生成: {exc}")
                        runtime_bundle = None

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

            # 获取设备到端口映射 + 设备到 parser_family 映射（新主路径需要）
            device_port_map: Dict[str, List[int]] = {}
            device_family_map: Dict[str, str] = {}
            if task.protocol_version_id:
                device_port_map = await self.protocol_service.get_device_port_mapping(task.protocol_version_id)
                # get_devices_with_family 顺带推断 parser_family，我们复用
                devs_with_fam = await self.protocol_service.get_devices_with_family(task.protocol_version_id)
                for d in devs_with_fam:
                    fam = (d.get("protocol_family") or "").strip()
                    if fam:
                        device_family_map[d["device_name"]] = fam

            # =============== 构建解析计划（Phase 7：device_protocol_version_map 为主路径） ===============
            # 算法：
            #   1. 确定要解析的 (parser_family → version_id) 映射：
            #      - 优先取 task.device_protocol_version_map（新任务路径）
            #      - 老任务回落：扫 device_parser_map 的 ParserProfile，按其 protocol_family
            #        查 Available 最新版本。
            #   2. 对每个 family：
            #      - 加载 version，拿 version.parser_key
            #      - ParserRegistry.create(parser_key)
            #      - 注入 runtime_bundle（TSN 网络协议）+ device_bundle（版本化的 429 labels）
            #   3. 把要解析的设备端口按 device_family_map 分配到对应 parser_key。
            # merged_plan key 是字符串 parser_key；同一 parser_key 不会跨 family 复用。
            merged_plan: Dict[str, tuple] = {}
            device_bundle_by_family: Dict[str, Any] = {}
            families_to_parse: Dict[str, int] = {}
            # 记住每个 family 选中的设备（用于端口分配）
            selected_devices_by_family: Dict[str, List[str]] = {}

            # 1a) 新任务：task.device_protocol_version_map（仅白名单 family 走 version 绑定）
            dpv_map_raw_all: Dict[str, int] = {
                f: int(v)
                for f, v in (task.device_protocol_version_map or {}).items()
                if v is not None
            }
            dpv_map_raw: Dict[str, int] = {
                f: v for f, v in dpv_map_raw_all.items()
                if f in VERSION_BOUND_FAMILIES
            }
            ignored_families = sorted(set(dpv_map_raw_all.keys()) - set(dpv_map_raw.keys()))
            if ignored_families:
                print(
                    f"[Parser] device_protocol_version_map 忽略非 version-bound family: {ignored_families} "
                    f"(将继续走 legacy device_parser_map)"
                )
            families_to_parse.update(dpv_map_raw)

            # 1b) 老任务回落：device_parser_map 的 profile.protocol_family
            legacy_pid_to_family: Dict[int, str] = {}
            if task.device_parser_map:
                from .device_protocol_service import (
                    get_active_device_version_by_parser_family,
                )
                for dev_name, pid in task.device_parser_map.items():
                    if pid is None:
                        continue
                    pid_int = int(pid)
                    profile_fb = await self.get_parser_profile(pid_int)
                    if not profile_fb or not profile_fb.protocol_family:
                        continue
                    fam = profile_fb.protocol_family
                    if fam in VERSION_BOUND_FAMILIES:
                        # 这些 family 的执行语义由 device_protocol_version_map 控制
                        continue
                    legacy_pid_to_family[pid_int] = fam
                    selected_devices_by_family.setdefault(fam, []).append(dev_name)
                    if fam not in families_to_parse:
                        fb_ver = await get_active_device_version_by_parser_family(
                            self.db, fam
                        )
                        if fb_ver is not None:
                            families_to_parse[fam] = fb_ver.id
                            print(
                                f"[Parser] 老任务回落：parser_family={fam} "
                                f"→ version_id={fb_ver.id}（最新 Available）"
                            )

            # 1c) 新任务：通过 device_family_map + selected_devices 反推每个 family 选中的设备
            task_selected_devices = list(task.selected_devices or [])
            if dpv_map_raw and task_selected_devices:
                for dev_name in task_selected_devices:
                    fam = device_family_map.get(dev_name)
                    if fam and fam in dpv_map_raw:
                        selected_devices_by_family.setdefault(fam, []).append(dev_name)

            if not families_to_parse:
                await self.update_task_status(
                    task_id,
                    "failed",
                    error_message="任务既无 device_protocol_version_map 也无 device_parser_map，无法构建解析计划",
                )
                return False

            # 2) 为每个 family 加载 version，实例化 parser，注入 bundle
            from app.models.device_protocol import DeviceProtocolVersion  # noqa: WPS433
            print(f"[Parser] 构建解析计划（families={list(families_to_parse.keys())}）")
            for fam, version_id in families_to_parse.items():
                ver_row = await self.db.execute(
                    select(DeviceProtocolVersion).where(
                        DeviceProtocolVersion.id == int(version_id)
                    )
                )
                ver = ver_row.scalar_one_or_none()
                if ver is None:
                    print(f"[Parser]   警告: family={fam} version_id={version_id} 不存在，跳过")
                    continue
                parser_key = (ver.parser_key or "").strip()
                if not parser_key:
                    print(
                        f"[Parser]   警告: family={fam} version_id={version_id} 未绑定 parser_key，"
                        f"跳过（请在设备协议管理中配置）"
                    )
                    continue
                if parser_key in merged_plan:
                    # 两个 family 共用同一个 parser 是不应该发生的，但幂等处理
                    print(
                        f"[Parser]   注意: parser_key={parser_key} 已被前一个 family 占用，跳过 family={fam}"
                    )
                    continue
                parser = ParserRegistry.create(parser_key)
                if parser is None:
                    print(f"[Parser]   警告: parser_key={parser_key} 未注册，跳过 family={fam}")
                    continue
                try:
                    parser.set_bundle(runtime_bundle)
                except Exception as exc:  # noqa: BLE001
                    print(f"[Parser]   警告: {parser_key} set_bundle 失败: {exc}")
                dev_b = try_load_device_bundle(int(ver.id))
                if dev_b is not None:
                    device_bundle_by_family[fam] = dev_b
                    set_dev = getattr(parser, "set_device_bundle", None)
                    if callable(set_dev):
                        try:
                            set_dev(dev_b)
                            print(
                                f"[Parser]   {parser_key} (family={fam}) "
                                f"<- device_bundle v{ver.id} (labels={len(dev_b.labels)})"
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(
                                f"[Parser]   警告: {parser_key} set_device_bundle 失败: {exc}"
                            )
                else:
                    print(
                        f"[Parser]   警告: family={fam} version_id={ver.id} 的 device_bundle 加载失败 "
                        f"— 该 family 的 429 word 将整体跳过（bundle 为 ARINC429 解析唯一来源）"
                    )
                meta = ParserRegistry.metadata(parser_key) or {}
                display_name = meta.get("display_name") or parser_key
                merged_plan[parser_key] = (parser, set(), [], display_name, fam)

            # 3) 端口分配：把每个 family 选中的设备端口加到对应 parser_key 的 plan
            for parser_key, (parser, ports_set, dev_labels, display_name, fam) in list(merged_plan.items()):
                devs = selected_devices_by_family.get(fam, [])
                if not devs:
                    print(f"[Parser]   family={fam} 未选中任何设备 → parser_key={parser_key} 无端口可解析")
                    continue
                for dev_name in devs:
                    dev_ports = device_port_map.get(dev_name, [])
                    if not dev_ports:
                        print(f"[Parser]   设备 {dev_name} 在 TSN 网络协议里没有端口，跳过")
                        continue
                    ports_set.update(dev_ports)
                    dev_labels.append(dev_name)
                    print(
                        f"[Parser]   {dev_name} -> {display_name} "
                        f"(parser_key={parser_key}): 端口 {sorted(dev_ports)}"
                    )

            # 过滤掉未分配到任何端口的 parser（避免误走）
            for k in list(merged_plan.keys()):
                if not merged_plan[k][1]:
                    print(f"[Parser]   parser_key={k} 无端口，从计划中移除")
                    merged_plan.pop(k)

            if not merged_plan:
                await self.update_task_status(task_id, "failed", error_message="未能构建有效的解析计划")
                return False
            
            # 汇总所有需要解析的端口
            all_target_ports = set()
            for _, (_, ports, _, _, _) in merged_plan.items():
                all_target_ports.update(ports)
            
            target_ports_list = sorted(all_target_ports)
            print(f"[Parser] 目标端口({len(target_ports_list)}个): {target_ports_list}")
            
            # 构造 TSN 网络协议布局
            network_layout: Dict[int, List[FieldLayout]] = {}
            if task.protocol_version_id and target_ports_list:
                print(f"[Parser] 从 TSN 网络协议(版本ID={task.protocol_version_id})加载字段布局...")
                network_layout = await self._build_network_layout(
                    task.protocol_version_id, target_ports_list
                )
            
            # =============== 单次遍历解析（所有解析器共享一次文件读取） ===============
            total_records = 0
            spill_dir: Optional[Path] = None

            all_parsed_data, spill_dir = await self._parse_single_pass(
                task.file_path, merged_plan, network_layout, task_id=task_id
            )

            if not all_parsed_data:
                # 没有命中任何目标端口时，视为“解析完成但无匹配数据”，避免前端误判为失败。
                if spill_dir and spill_dir.exists():
                    import shutil
                    shutil.rmtree(spill_dir, ignore_errors=True)
                await self.update_task_status(
                    task_id,
                    "completed",
                    parsed_packets=0,
                    error_message="未找到匹配端口数据，请确认端口选择或数据内容",
                )
                self._cleanup_pcap(task.file_path)
                return True
            
            await self.update_task_status(task_id, "processing", progress=95)

            # --- 辅助：从溢出文件 + 内存中合并某个 (parser_key, port) 的全部记录 ---
            def _spill_slug(pk: str) -> str:
                """parser_key 中可能有 '.'，这里统一替换为 '_' 以作文件名。"""
                return pk.replace(".", "_").replace("/", "_")

            def _load_full_port(pk_: str, port_: int) -> List[Dict]:
                """将溢出文件中的记录读回并与内存记录合并，替换 all_parsed_data 中的列表。
                读回后删除溢出文件，避免 _save_results 重复读取。"""
                mem_recs = all_parsed_data.get(pk_, {}).get(port_, [])
                if not spill_dir:
                    return mem_recs
                slug = _spill_slug(pk_)
                s_files = sorted(spill_dir.glob(f"spill_{slug}_{port_}_*.parquet"))
                if not s_files:
                    return mem_recs
                reloaded: List[Dict] = []
                for sf in s_files:
                    t = pq.read_table(str(sf))
                    reloaded.extend(t.to_pylist())
                    sf.unlink(missing_ok=True)
                reloaded.extend(mem_recs)
                all_parsed_data.setdefault(pk_, {})[port_] = reloaded
                return reloaded

            # FCC 后处理：为每行 FCC 记录回填当前主飞控，同时构建 ATG 核对所需的事件列表
            fcc_pk: Optional[str] = None
            for pk_, (_, _, _, _, fam_) in merged_plan.items():
                if pk_ in all_parsed_data and (fam_ or "").lower() == "fcc":
                    fcc_pk = pk_
                    break

            main_fcc_changes: List[Dict[str, Any]] = []
            irs_selection_events: List[Dict[str, Any]] = []

            if fcc_pk and fcc_pk in all_parsed_data:
                fcc_all_rows: List[Dict[str, Any]] = []
                for port_fcc in list(all_parsed_data[fcc_pk].keys()):
                    recs_fcc = _load_full_port(fcc_pk, port_fcc)
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

                del fcc_all_rows
                print(f"[Parser] FCC 后处理: 回填 main_fcc 完成, "
                      f"{len(main_fcc_changes)} 次主飞控变更, {len(irs_selection_events)} 次 IRS 通道事件")

            # ATG 核对列
            atg_pk: Optional[str] = None
            for pk_, (parser, _, _, _, fam_) in merged_plan.items():
                if (fam_ or "").lower() == "atg" and pk_ in all_parsed_data:
                    atg_pk = pk_
                    break
            if atg_pk is not None:
                irs_data_by_key: Dict[str, List[Dict[str, Any]]] = {}
                rtk_data_all: List[Dict[str, Any]] = []
                for pk2, (parser2, _, _, _, fam2) in merged_plan.items():
                    family2 = (fam2 or "").lower()
                    if family2 not in {"irs", "rtk"}:
                        continue
                    if pk2 not in all_parsed_data:
                        continue
                    for port2 in list(all_parsed_data[pk2].keys()):
                        recs2 = _load_full_port(pk2, port2)
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

                for port_number in list(all_parsed_data[atg_pk].keys()):
                    records = _load_full_port(atg_pk, port_number)
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
                del irs_data_by_key, rtk_data_all
                print(f"[Parser] ATG 核对列计算完成")

            # 保存结果（进度 96% → 99%）
            save_items = []
            for pk_, parsed_data in all_parsed_data.items():
                slug = _spill_slug(pk_)
                for port_number, records in parsed_data.items():
                    has_spill = bool(
                        spill_dir and list(spill_dir.glob(f"spill_{slug}_{port_number}_*.parquet"))
                    )
                    if records or has_spill:
                        save_items.append((pk_, port_number, records))
            save_total = len(save_items) or 1

            for save_idx, (pk_, port_number, records) in enumerate(save_items):
                plan_entry = merged_plan.get(pk_)
                parser_inst = plan_entry[0] if plan_entry else None
                display_name = plan_entry[3] if plan_entry else pk_

                result_file, row_count = await self._save_results(
                    task_id, port_number, records,
                    parser_slug=_spill_slug(pk_), parser=parser_inst,
                    spill_dir=spill_dir,
                )

                source_device = port_device_map.get(port_number)

                parse_result = ParseResult(
                    task_id=task_id,
                    port_number=port_number,
                    message_name=f"{display_name} - Port {port_number}",
                    parser_profile_id=None,  # Phase 7：不再引用 parser_profiles 表
                    parser_profile_name=display_name,
                    source_device=source_device,
                    record_count=row_count,
                    result_file=result_file,
                    time_start=datetime.fromtimestamp(records[0].get('timestamp', 0)) if records else None,
                    time_end=datetime.fromtimestamp(records[-1].get('timestamp', 0)) if records else None,
                )
                self.db.add(parse_result)
                total_records += row_count

                # 释放已保存端口的内存，让 GC 尽早回收
                del records
                if pk_ in all_parsed_data and port_number in all_parsed_data[pk_]:
                    del all_parsed_data[pk_][port_number]

                save_pct = 96 + int((save_idx + 1) / save_total * 3)
                await self.update_task_status(task_id, "processing", progress=min(save_pct, 99))

            del save_items
            # 清理溢出临时目录
            if spill_dir and spill_dir.exists():
                import shutil
                shutil.rmtree(spill_dir, ignore_errors=True)

            await self.db.commit()
            await self.update_task_status(
                task_id, "completed", parsed_packets=total_records, stage=None
            )
            print(f"[Parser] 解析完成，共 {total_records} 条记录（原始文件已保留供重新解析）")
            return True

        except TaskCancelled:
            print(f"[Parser] 任务 {task_id} 已被用户取消")
            if spill_dir and spill_dir.exists():
                import shutil
                shutil.rmtree(spill_dir, ignore_errors=True)
            await self.update_task_status(
                task_id, "cancelled", error_message="任务已被取消", stage=None
            )
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            if spill_dir and spill_dir.exists():
                import shutil
                shutil.rmtree(spill_dir, ignore_errors=True)
            await self.update_task_status(
                task_id, "failed", error_message=str(e), stage=None
            )
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
    
    @staticmethod
    def _spill_records(records: List[Dict], spill_dir: Path, parser_key: str, port: int,
                       spill_counts: Dict[Tuple[str, int], int]) -> None:
        """将内存中的记录溢出到临时 Parquet 文件，然后清空列表。

        ``parser_key`` 可能含点号（如 ``adc_v2.2``），文件名里统一换成 ``_``。
        ``spill_counts`` 的 key 直接用原始 ``parser_key``，外部读取也使用原串。
        """
        key = (parser_key, port)
        idx = spill_counts.get(key, 0)
        spill_counts[key] = idx + 1
        slug = parser_key.replace(".", "_").replace("/", "_")
        spill_path = spill_dir / f"spill_{slug}_{port}_{idx}.parquet"
        table = pa.Table.from_pylist(records)
        pq.write_table(table, str(spill_path))
        records.clear()

    async def _parse_single_pass(
        self,
        file_path: str,
        merged_plan: Dict[str, tuple],
        network_layout: Dict[int, List[FieldLayout]],
        task_id: Optional[int] = None,
    ) -> Tuple[Dict[str, Dict[int, List[Dict]]], Optional[Path]]:
        """单次遍历解析：所有解析器共享一次文件遍历，按端口分发到对应解析器。
        
        当单端口记录数超过 _SPILL_THRESHOLD 时，自动溢出到临时 Parquet 文件
        以控制峰值内存。
        
        Args:
            file_path: pcapng/pcap 文件路径
            merged_plan: {parser_key: (parser, ports_set, dev_labels, display_name, family)}
            network_layout: {port: [FieldLayout, ...]}
            
        Returns:
            (data_dict, spill_dir_or_None)
            data_dict: {parser_key: {port: [record_dict, ...]}}  -- 内存中剩余记录
            spill_dir: 溢出临时目录（None 表示无溢出）
        """
        try:
            import dpkt
        except ImportError:
            print("[Parser] dpkt未安装")
            return {}, None

        def _slug(pk: str) -> str:
            return pk.replace(".", "_").replace("/", "_")

        # 步骤A: 构建端口分发表 {port: (parser, parser_key, field_layout)}
        port_dispatch: Dict[int, tuple] = {}
        for pk, (parser, plan_ports, dev_labels, display_name, fam) in merged_plan.items():
            if plan_ports is None:
                continue
            for port in plan_ports:
                layout = network_layout.get(port)
                port_dispatch[port] = (parser, pk, layout)
        
        target_set = set(port_dispatch.keys())
        if not target_set:
            print("[Parser] 无目标端口，跳过解析")
            return {}, None
        
        print(f"[Parser] 单次遍历模式，目标端口({len(target_set)}个): {sorted(target_set)}")
        dispatched: Dict[str, set] = {pk: set() for pk in merged_plan}
        for port, (_, pk, _) in port_dispatch.items():
            dispatched[pk].add(port)
        for pk, (_, _, dev_labels, display_name, _) in merged_plan.items():
            if pk in dispatched:
                print(f"[Parser]   {display_name} ({', '.join(dev_labels)}) -> 端口 {sorted(dispatched[pk])}")
        
        # 初始化结果容器
        all_parsed_data: Dict[str, Dict[int, List[Dict]]] = {}
        for pk, (_, plan_ports, _, _, _) in merged_plan.items():
            if plan_ports is None:
                continue
            all_parsed_data[pk] = {port: [] for port in plan_ports}
        
        # 检测哪些解析器支持拼包模式
        reassembly_parsers: set = set()
        for pk, (parser, _, _, display_name, _) in merged_plan.items():
            if hasattr(parser, 'feed_packet'):
                reassembly_parsers.add(pk)
                parser.reset_buffers()
                print(f"[Parser]   {display_name}: 使用拼包模式 (feed_packet)")
        
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

        # 溢出落盘：当单端口记录数超过阈值时写入临时 Parquet
        import tempfile
        spill_dir: Optional[Path] = None
        spill_counts: Dict[Tuple[str, int], int] = {}

        def _maybe_spill(pk_: str, port_: int) -> None:
            nonlocal spill_dir
            recs = all_parsed_data[pk_][port_]
            if len(recs) >= _SPILL_THRESHOLD:
                if spill_dir is None:
                    spill_dir = Path(tempfile.mkdtemp(prefix="tsn_spill_"))
                self._spill_records(recs, spill_dir, pk_, port_, spill_counts)

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
                        return {}, None
                
                # ↑↑↑ _parse_single_pass 内部：以 parser_key(str) 作为 all_parsed_data 主键 ↑↑↑
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
                            _maybe_spill(pid, dst_port)
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
                                _maybe_spill(pid, dst_port)
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
                            _maybe_spill(pid, port)
            
            print(f"[Parser] 单次遍历完成: 共 {packet_count} 包, "
                  f"匹配 {matched_count}, 预过滤跳过 {skipped_by_prefilter}")
            if spill_counts:
                total_spills = sum(spill_counts.values())
                print(f"[Parser] 溢出落盘: {total_spills} 个临时文件 -> {spill_dir}")

            for pid, port_data in all_parsed_data.items():
                for port, records in port_data.items():
                    spill_n = spill_counts.get((pid, port), 0)
                    mem_n = len(records)
                    if mem_n or spill_n:
                        extra = f" + {spill_n} 个溢出文件" if spill_n else ""
                        print(f"[Parser]   解析器{pid} 端口{port}: 内存 {mem_n} 条{extra}")

            # 清理空端口（内存中无记录且无溢出文件的端口）
            result: Dict[str, Dict[int, List[Dict]]] = {}
            for pid, port_data in all_parsed_data.items():
                cleaned = {}
                for p, recs in port_data.items():
                    if recs or (pid, p) in spill_counts:
                        cleaned[p] = recs
                if cleaned:
                    result[pid] = cleaned

            return result, spill_dir

        except Exception as e:
            print(f"[Parser] 单次遍历解析错误: {e}")
            import traceback
            traceback.print_exc()
            if spill_dir and spill_dir.exists():
                import shutil
                shutil.rmtree(spill_dir, ignore_errors=True)
            return {}, None
    
    async def _save_results(
        self,
        task_id: int,
        port_number: int,
        records: List[Dict],
        parser_slug: Optional[str] = None,
        parser: Any = None,
        spill_dir: Optional[Path] = None,
    ) -> Tuple[str, int]:
        """保存解析结果为Parquet文件，按端口裁剪列。

        如果存在溢出临时文件，先将内存中剩余记录写为临时 Parquet，
        再用 pyarrow.dataset 合并所有分片为最终文件。

        ``parser_slug`` 是从 ``parser_key`` 生成的文件名安全字符串（Phase 7
        之后用它替代过去的 ``parser_id``）。

        Returns:
            (result_file_path, total_row_count)
        """
        result_dir = DATA_DIR / "results" / str(task_id)
        result_dir.mkdir(parents=True, exist_ok=True)

        if parser_slug:
            result_file = result_dir / f"port_{port_number}_parser_{parser_slug}.parquet"
        else:
            result_file = result_dir / f"port_{port_number}.parquet"

        # 确定需要保留的列
        target_cols = None
        if parser is not None and hasattr(parser, "get_output_columns"):
            try:
                target_cols = parser.get_output_columns(port_number)
            except Exception:
                target_cols = None

        # 收集溢出文件
        spill_files: List[Path] = []
        if spill_dir and spill_dir.exists() and parser_slug:
            prefix = f"spill_{parser_slug}_{port_number}_"
            spill_files = sorted(spill_dir.glob(f"{prefix}*.parquet"))

        if not spill_files:
            # 无溢出：直接从内存写入（原有路径）
            if target_cols:
                trimmed = [{k: r.get(k) for k in target_cols} for r in records]
            else:
                trimmed = records
            row_count = len(trimmed)
            print(f"[Parser] 保存端口 {port_number}: {row_count} 行"
                  + (f", {len(target_cols)} 列" if target_cols else ""))
            table = pa.Table.from_pylist(trimmed)
            table = self._cast_datetime_col(table)
            pq.write_table(table, str(result_file))
            return str(result_file), row_count

        # 有溢出：合并溢出文件 + 内存中剩余记录
        all_tables: List[pa.Table] = []
        for sf in spill_files:
            t = pq.read_table(str(sf))
            if target_cols:
                keep = [c for c in target_cols if c in t.schema.names]
                t = t.select(keep) if keep else t
            all_tables.append(t)

        if records:
            if target_cols:
                trimmed = [{k: r.get(k) for k in target_cols} for r in records]
            else:
                trimmed = records
            all_tables.append(pa.Table.from_pylist(trimmed))

        merged = pa.concat_tables(all_tables, promote_options="default")
        row_count = merged.num_rows
        print(f"[Parser] 保存端口 {port_number}: {row_count} 行 (合并 {len(spill_files)} 个溢出文件)"
              + (f", {len(target_cols)} 列" if target_cols else ""))
        merged = self._cast_datetime_col(merged)
        pq.write_table(merged, str(result_file))

        # 清理已合并的溢出文件
        for sf in spill_files:
            sf.unlink(missing_ok=True)

        return str(result_file), row_count

    @staticmethod
    def _cast_datetime_col(table: pa.Table) -> pa.Table:
        """将 BeijingDateTime 列统一转为 string 类型。"""
        if "BeijingDateTime" in table.schema.names:
            idx = table.schema.get_field_index("BeijingDateTime")
            table = table.set_column(
                idx, pa.field("BeijingDateTime", pa.string()),
                table.column("BeijingDateTime").cast(pa.string()),
            )
        return table
    
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
                with open(export_file, "w", encoding="utf-8-sig", newline="") as f:
                    f.write(",".join(_rename_export_time_col(export_schema_names)) + "\n")
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
