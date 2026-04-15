# -*- coding: utf-8 -*-
"""
自动飞行性能分析服务
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import DATA_DIR, UPLOAD_DIR
from ..models import (
    AutoFlightAnalysisTask,
    TouchdownAnalysisResult,
    SteadyStateAnalysisResult,
    ParseResult,
)
from .event_rules import AutoFlightAnalyzer
from .pcap_reader import pcap_to_port_dataframes, iter_udp_packets
from .parsers.irs_parser import IRSParser


AUTO_FLIGHT_PORTS = {9031: "FCC1", 9032: "FCC2", 9033: "FCC3"}
IRS_PORT_HINTS = {7004: "IRS1", 7005: "IRS2", 7006: "IRS3"}
TSN_HEADER_LEN = 8


def _u8(data: bytes, idx1: int) -> int:
    return int(data[idx1 - 1])


def _f32(data: bytes, idx1: int) -> float:
    import struct
    start = idx1 - 1
    return float(struct.unpack("<f", data[start:start + 4])[0])


def _decode_auto_flight_raw(raw_hex: str, port: int) -> Optional[dict]:
    try:
        b = bytes.fromhex(raw_hex or "")
    except Exception:
        return None
    if len(b) < TSN_HEADER_LEN + 124:
        return None
    d = b[TSN_HEADER_LEN:TSN_HEADER_LEN + 124]
    try:
        return {
            "source_port": port,
            "source_fcc": AUTO_FLIGHT_PORTS.get(port),
            "ap_engaged": _u8(d, 1),
            "at_engaged": _u8(d, 2),
            "air_ground": _u8(d, 3),
            "flight_phase": _u8(d, 4),
            "auto_mode": _u8(d, 5),
            "lat_mode_active": _u8(d, 8),
            "lon_mode_active": _u8(d, 10),
            "thr_mode_active": _u8(d, 12),
            "af_warning": _u8(d, 13),
            "lat_track_error_m": _f32(d, 14),
            "vert_track_error_m": _f32(d, 18),
            "speed_cmd_mps": _f32(d, 22),
            "current_altitude_m": _f32(d, 56),
            "current_airspeed_mps": _f32(d, 60),
            "current_groundspeed_mps": _f32(d, 68),
        }
    except Exception:
        return None


class AutoFlightAnalysisService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task_from_pcap(
        self,
        filename: str,
        file_path: str,
        source_type: str = "standalone",
    ) -> AutoFlightAnalysisTask:
        task = AutoFlightAnalysisTask(
            parse_task_id=None,
            pcap_filename=filename,
            pcap_file_path=file_path,
            name=f"{filename} 自动飞行性能分析",
            source_type=source_type,
            status="pending",
            progress=0,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def create_task_from_parse(self, parse_task_id: int) -> AutoFlightAnalysisTask:
        task = AutoFlightAnalysisTask(
            parse_task_id=parse_task_id,
            pcap_filename=None,
            pcap_file_path=None,
            name=f"解析任务#{parse_task_id} 自动飞行性能分析",
            source_type="parse_task",
            status="pending",
            progress=0,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def list_tasks(self, page: int = 1, page_size: int = 20) -> Tuple[List[AutoFlightAnalysisTask], int]:
        filt = True
        total = (
            await self.db.execute(select(func.count()).select_from(AutoFlightAnalysisTask).where(filt))
        ).scalar() or 0
        offset = (page - 1) * page_size
        rows = (
            await self.db.execute(
                select(AutoFlightAnalysisTask)
                .where(filt)
                .order_by(AutoFlightAnalysisTask.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), int(total)

    async def get_task(self, task_id: int) -> Optional[AutoFlightAnalysisTask]:
        return (
            await self.db.execute(
                select(AutoFlightAnalysisTask).where(AutoFlightAnalysisTask.id == task_id)
            )
        ).scalar_one_or_none()

    async def get_touchdowns(self, task_id: int) -> List[TouchdownAnalysisResult]:
        return (
            await self.db.execute(
                select(TouchdownAnalysisResult)
                .where(TouchdownAnalysisResult.analysis_task_id == task_id)
                .order_by(TouchdownAnalysisResult.sequence)
            )
        ).scalars().all()

    async def get_steady_states(self, task_id: int) -> List[SteadyStateAnalysisResult]:
        return (
            await self.db.execute(
                select(SteadyStateAnalysisResult)
                .where(SteadyStateAnalysisResult.analysis_task_id == task_id)
                .order_by(SteadyStateAnalysisResult.sequence)
            )
        ).scalars().all()

    async def run_analysis(self, task_id: int) -> bool:
        task = await self.get_task(task_id)
        if not task:
            return False
        task.status = "processing"
        task.progress = 5
        await self.db.commit()

        temp_pcap_path = Path(task.pcap_file_path) if task.pcap_file_path else None
        try:
            if task.parse_task_id:
                task.progress = 15
                await self.db.commit()
                auto_df, irs_by_name = await self._load_from_parse_task(task.parse_task_id)
                task.progress = 65
                await self.db.commit()
            else:
                if not task.pcap_file_path:
                    raise RuntimeError("任务未配置 pcap 文件路径")
                task.progress = 15
                await self.db.commit()
                auto_df = self._load_auto_from_pcap(task.pcap_file_path)

                task.progress = 40
                await self.db.commit()
                irs_by_name = self._collect_irs_from_pcap(task.pcap_file_path)

                task.progress = 65
                await self.db.commit()

            task.progress = 80
            await self.db.commit()

            analyzer = AutoFlightAnalyzer()
            out = analyzer.analyze(auto_df, irs_by_name)

            task.progress = 90
            await self.db.commit()
            await self._persist_outputs(task, out)
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            task.status = "failed"
            task.error_message = str(e)
            await self.db.commit()
            return False
        finally:
            if temp_pcap_path is not None:
                try:
                    shared_dir = (UPLOAD_DIR / "shared_tsn").resolve()
                    if temp_pcap_path.resolve().is_relative_to(shared_dir):
                        print(f"[AutoFlightAnalysis] 跳过共享文件: {temp_pcap_path.name}")
                    elif temp_pcap_path.is_file():
                        temp_pcap_path.unlink()
                        print(f"[AutoFlightAnalysis] 已删除临时文件: {temp_pcap_path}")
                except Exception as cleanup_err:
                    print(f"[AutoFlightAnalysis] 清理临时文件失败: {cleanup_err}")

    def _load_auto_from_pcap(self, pcap_path: str) -> pd.DataFrame:
        # 自动飞行端口直接按固定端口提取。
        required = set(AUTO_FLIGHT_PORTS.keys())
        port_map = pcap_to_port_dataframes(pcap_path, required)

        # 自动飞行数据
        auto_rows: List[dict] = []
        for p in AUTO_FLIGHT_PORTS.keys():
            df = port_map.get(p)
            if df is None or df.empty:
                continue
            for row in df.itertuples(index=False):
                d = _decode_auto_flight_raw(getattr(row, "raw_data", ""), p)
                if d is None:
                    continue
                d["timestamp"] = float(getattr(row, "timestamp"))
                auto_rows.append(d)
        return pd.DataFrame(auto_rows).sort_values("timestamp").reset_index(drop=True) if auto_rows else pd.DataFrame(columns=["timestamp"])

    def _collect_irs_from_pcap(self, pcap_path: str) -> Dict[str, pd.DataFrame]:
        parser = IRSParser()
        seen_ports: set[int] = set()
        dev_rows: Dict[str, List[dict]] = {"IRS1": [], "IRS2": [], "IRS3": []}

        # IRSParser.device_id 约定:
        # 0 -> 惯导3, 1 -> 惯导1, 2 -> 惯导2
        device_to_name = {0: "IRS3", 1: "IRS1", 2: "IRS2"}

        def _append_records(records: List[dict], port: int) -> None:
            for rec in records:
                dev_id = rec.get("device_id")
                irs_name = device_to_name.get(dev_id)
                if not irs_name:
                    continue
                dev_rows[irs_name].append({
                    "timestamp": rec.get("timestamp"),
                    "vertical_velocity": rec.get("vertical_velocity"),
                    "accel_z": rec.get("accel_z"),
                    "source_port": port,
                    "device_id": dev_id,
                })

        for ts, dport, payload in iter_udp_packets(pcap_path):
            seen_ports.add(dport)
            try:
                records = parser.feed_packet(payload, dport, ts)
            except Exception:
                records = []
            if records:
                _append_records(records, dport)

        # 结束后刷新缓冲区，尽量提取尾部残留完整帧
        for p in seen_ports:
            try:
                flushed = parser.flush_buffer(p)
            except Exception:
                flushed = []
            if flushed:
                _append_records(flushed, p)

        out: Dict[str, pd.DataFrame] = {}
        for name in ("IRS1", "IRS2", "IRS3"):
            rows = dev_rows[name]
            if not rows:
                out[name] = pd.DataFrame(columns=["timestamp", "vertical_velocity", "accel_z", "source_port", "device_id"])
                continue
            df = pd.DataFrame(rows)
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
            out[name] = df
        return out

    async def _load_from_parse_task(self, parse_task_id: int) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        # 读取 parse_results，找到自动飞行与 IRS 相关端口 parquet
        parse_results = (
            await self.db.execute(
                select(ParseResult).where(ParseResult.task_id == parse_task_id)
            )
        ).scalars().all()

        auto_frames: List[pd.DataFrame] = []
        irs_by_name: Dict[str, pd.DataFrame] = {"IRS1": pd.DataFrame(), "IRS2": pd.DataFrame(), "IRS3": pd.DataFrame()}

        for r in parse_results:
            if not r.result_file:
                continue
            f = Path(r.result_file)
            if not f.is_file():
                # 兼容老数据：尝试按标准路径寻找
                fallback = DATA_DIR / "results" / str(parse_task_id) / f"port_{r.port_number}.parquet"
                if fallback.is_file():
                    f = fallback
                else:
                    continue
            try:
                df = pd.read_parquet(f)
            except Exception:
                continue

            if r.port_number in AUTO_FLIGHT_PORTS:
                need = [c for c in [
                    "timestamp", "ap_engaged", "at_engaged", "air_ground",
                    "lon_mode_active", "af_warning",
                    "lat_track_error_m", "vert_track_error_m",
                    "speed_cmd_mps", "current_airspeed_mps",
                ] if c in df.columns]
                if need:
                    tdf = df[need].copy()
                    tdf["source_port"] = r.port_number
                    auto_frames.append(tdf)
            if r.port_number in IRS_PORT_HINTS:
                need = [c for c in ["timestamp", "vertical_velocity", "accel_z"] if c in df.columns]
                if need:
                    irs_by_name[IRS_PORT_HINTS[r.port_number]] = df[need].copy()

        auto_df = pd.concat(auto_frames, ignore_index=True) if auto_frames else pd.DataFrame(columns=["timestamp"])
        if not auto_df.empty and "timestamp" in auto_df.columns:
            auto_df = auto_df.sort_values("timestamp").reset_index(drop=True)
        return auto_df, irs_by_name

    async def _clear_old_results(self, task_id: int) -> None:
        await self.db.execute(
            TouchdownAnalysisResult.__table__.delete().where(
                TouchdownAnalysisResult.analysis_task_id == task_id
            )
        )
        await self.db.execute(
            SteadyStateAnalysisResult.__table__.delete().where(
                SteadyStateAnalysisResult.analysis_task_id == task_id
            )
        )
        await self.db.commit()

    async def _persist_outputs(self, task: AutoFlightAnalysisTask, out: Dict[str, any]) -> None:
        await self._clear_old_results(task.id)

        for d in out.get("touchdowns", []):
            row = TouchdownAnalysisResult(
                analysis_task_id=task.id,
                sequence=d.get("sequence", 0),
                touchdown_ts=d.get("touchdown_ts"),
                touchdown_time=d.get("touchdown_time"),
                irs1_vz=d.get("irs1_vz"),
                irs2_vz=d.get("irs2_vz"),
                irs3_vz=d.get("irs3_vz"),
                vz_spread=d.get("vz_spread"),
                irs1_az_peak=d.get("irs1_az_peak"),
                irs2_az_peak=d.get("irs2_az_peak"),
                irs3_az_peak=d.get("irs3_az_peak"),
                az_peak_spread=d.get("az_peak_spread"),
                rating=d.get("rating", "normal"),
                summary=d.get("summary"),
                chart_data=d.get("chart_data"),
            )
            self.db.add(row)

        for d in out.get("steady_states", []):
            row = SteadyStateAnalysisResult(
                analysis_task_id=task.id,
                sequence=d.get("sequence", 0),
                start_ts=d.get("start_ts"),
                end_ts=d.get("end_ts"),
                start_time=d.get("start_time"),
                end_time=d.get("end_time"),
                duration_s=d.get("duration_s", 0.0),
                mode_label=d.get("mode_label"),
                alt_bias=d.get("alt_bias"),
                alt_rms=d.get("alt_rms"),
                alt_max_abs=d.get("alt_max_abs"),
                lat_bias=d.get("lat_bias"),
                lat_rms=d.get("lat_rms"),
                lat_max_abs=d.get("lat_max_abs"),
                spd_bias=d.get("spd_bias"),
                spd_rms=d.get("spd_rms"),
                spd_max_abs=d.get("spd_max_abs"),
                rating=d.get("rating", "normal"),
                summary=d.get("summary"),
                chart_data=d.get("chart_data"),
            )
            self.db.add(row)

        task.touchdown_count = int(out.get("summary", {}).get("touchdown_count", 0))
        task.steady_count = int(out.get("summary", {}).get("steady_count", 0))
        task.status = "completed"
        task.progress = 100
        task.completed_at = datetime.utcnow()
        task.error_message = None
        await self.db.commit()
