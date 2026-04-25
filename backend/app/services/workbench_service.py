# -*- coding: utf-8 -*-
"""试验工作台服务：解析任务级别的总览 + 事件分析总结。

- `build_overview(db, parse_task_id)` 扫描 `ParseResult` 定位 IRS/ADC 端口，
  读取 parquet 做统计、飞行阶段、异常、叙述、轨迹与姿态降采样。
- `build_events_summary(db, parse_task_id)` 并发聚合 FMS/FCC/自动飞行/TSN 异常检查
  四类分析任务，每类返回状态、计数和前 N 条事件（带深链信息）。
- 移植自同事的 CSV 飞行架次分析平台（flight_data_webapp/app.py）的阶段/异常/叙述算法，
  数据源切换为 IRS parquet（权威位置/姿态源）+ ADC parquet（空速/马赫）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import DATA_DIR
from ..models import (
    AutoFlightAnalysisTask,
    CompareGapRecord,
    ComparePortResult,
    ComparePortTimingResult,
    CompareTask,
    FccEventAnalysisTask,
    FccEventCheckResult,
    FccEventTimelineEvent,
    FmsEventAnalysisTask,
    FmsEventCheckResult,
    FmsEventTimelineEvent,
    ParseResult,
    ParseTask,
    SharedSortie,
    SharedTsnFile,
    SteadyStateAnalysisResult,
    TouchdownAnalysisResult,
)
from .workbench_summaries import (
    build_auto_flight_narrative,
    build_compare_narrative,
    build_fcc_narrative,
    build_fms_narrative,
)


MAX_SERIES_POINTS = 3000  # 与 CSV 平台一致
ALTITUDE_JUMP_THRESHOLD = 50.0  # m/s，沿用 CSV 平台阈值
DEFAULT_STATUS_COLS = (
    "attitude_status_enum",
    "heading_status_enum",
    "position_status_enum",
    "altitude_status_enum",
)

# 展示用：TSN/解析库 timestamp 为 UTC 秒 → 统一格式化为北京时间（UTC+8）
_TZ_BEIJING = timezone(timedelta(hours=8))


# ──────────────────────────── 通用工具 ────────────────────────────

def _fmt_time(seconds: Optional[float]) -> str:
    if seconds is None or not np.isfinite(seconds):
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def _fmt_timestamp_beijing_utc(ts: Optional[float]) -> str:
    """将解析库中的 UTC Unix 秒格式化为北京时间字符串（含毫秒）。"""
    if ts is None or not np.isfinite(float(ts)):
        return "N/A"
    try:
        dt_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        dt_bj = dt_utc.astimezone(_TZ_BEIJING)
        return dt_bj.strftime("%Y-%m-%d %H:%M:%S") + f".{int(dt_bj.microsecond / 1000):03d}"
    except (OSError, OverflowError, ValueError):
        return "N/A"


def _fmt_timestamp_utc_iso(ts: Optional[float]) -> str:
    if ts is None or not np.isfinite(float(ts)):
        return "N/A"
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OSError, OverflowError, ValueError):
        return "N/A"


def _fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None or not np.isfinite(seconds):
        return "N/A"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}min"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}min"


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _dt_to_seconds(dt: Optional[datetime]) -> Optional[float]:
    if dt is None:
        return None
    try:
        return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
    except Exception:
        return None


def _dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _downsample_indices(n: int, limit: int = MAX_SERIES_POINTS) -> np.ndarray:
    if n <= limit:
        return np.arange(n)
    step = max(1, n // limit)
    return np.arange(0, n, step)


def _resolve_parquet_path(result_file: Optional[str], task_id: int, port: int) -> Optional[Path]:
    """兼容新旧路径/只存相对路径/结果目录迁移的情况。"""
    candidates: List[Path] = []
    if result_file:
        candidates.append(Path(result_file))
    candidates.append(DATA_DIR / "results" / str(task_id) / f"port_{port}.parquet")
    results_dir = DATA_DIR / "results" / str(task_id)
    if results_dir.is_dir():
        candidates.extend(results_dir.glob(f"port_{port}_parser_*.parquet"))
    for p in candidates:
        if p and Path(p).is_file():
            return Path(p)
    return None


# ──────────────────────────── IRS/ADC 端口识别 ────────────────────────────

def _is_irs_result(r: ParseResult) -> bool:
    text = f"{r.parser_profile_name or ''} {r.message_name or ''} {r.source_device or ''}".lower()
    return any(kw in text for kw in ("irs", "惯导", "惯性", "inertial"))


def _is_adc_result(r: ParseResult) -> bool:
    text = f"{r.parser_profile_name or ''} {r.message_name or ''} {r.source_device or ''}".lower()
    return any(kw in text for kw in ("adc", "atg_cpe", "atg cpe", "air_data", "大气"))


def _pick_primary(results: List[ParseResult]) -> Optional[ParseResult]:
    if not results:
        return None
    return max(results, key=lambda r: int(r.record_count or 0))


# ──────────────────────────── 列识别（pandas 兜底） ────────────────────────────

def _resolve_column(cols: List[str], prefers: List[str], patterns: List[str] = None) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    for p in prefers:
        if p.lower() in low:
            return low[p.lower()]
    if patterns:
        import re as _re
        for pat in patterns:
            reg = _re.compile(pat, _re.IGNORECASE)
            for c in cols:
                if reg.search(c):
                    return c
    return None


def _altitude_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(
        cols,
        ["altitude", "alt_m", "altitude_m", "geo_altitude"],
        [r"altitude|高度|海拔"],
    )


def _latitude_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["latitude", "lat"], [r"latitude|lat"])


def _longitude_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["longitude", "lon"], [r"longitude|lon"])


def _heading_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["heading", "yaw", "hdg", "psi"], [r"heading|yaw|航向|偏航"])


def _pitch_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["pitch"], [r"pitch|俯仰|ptch"])


def _roll_col(cols: List[str]) -> Optional[str]:
    low = {c.lower(): c for c in cols}
    if "roll" in low:
        return low["roll"]
    import re as _re
    reg = _re.compile(r"roll|滚转|bank", _re.IGNORECASE)
    for c in cols:
        cl = c.lower()
        if reg.search(c) and "rate" not in cl and "rpm" not in cl:
            return c
    return None


def _groundspeed_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(
        cols,
        ["ground_speed", "groundspeed", "speed", "gps_speed"],
        [r"^speed$|ground.?speed|地速"],
    )


def _east_velocity_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["east_velocity", "velocity_east", "ve"], [r"east.*vel|vel.*east"])


def _north_velocity_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["north_velocity", "velocity_north", "vn"], [r"north.*vel|vel.*north"])


def _airspeed_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(
        cols,
        ["air_speed", "airspeed", "true_airspeed", "tas"],
        [r"air.?speed|空速"],
    )


def _mach_col(cols: List[str]) -> Optional[str]:
    return _resolve_column(cols, ["mach", "mach_number"], [r"mach|马赫"])


# ──────────────────────────── 算法移植（阶段/异常/叙述） ────────────────────────────

def _detect_flight_phases(
    times: np.ndarray, altitudes: np.ndarray, speeds: Optional[np.ndarray]
) -> List[Dict[str, Any]]:
    """移植 flight_data_webapp/app.py:detect_flight_phases。"""
    if times is None or len(times) < 10:
        return []

    alt = pd.Series(altitudes, dtype=float)
    spd = pd.Series(speeds, dtype=float) if speeds is not None else pd.Series(np.zeros(len(times)))
    alt_smooth = alt.rolling(window=min(30, len(alt) // 5 + 1), min_periods=1, center=True).mean()

    dt = np.diff(times)
    da = np.diff(alt_smooth.values)
    vrate = np.zeros(len(times))
    valid = dt > 0.01
    vrate[1:][valid] = da[valid] / dt[valid]
    vrate_smooth = pd.Series(vrate).rolling(window=min(50, len(vrate) // 5 + 1), min_periods=1, center=True).mean()

    ground_alt = float(np.percentile(alt.iloc[: min(50, len(alt))], 50))

    phases: List[Dict[str, Any]] = []
    state = "Ground"
    start_idx = 0

    for i in range(len(times)):
        h = alt_smooth.iloc[i] - ground_alt
        v = spd.iloc[i]
        vr = vrate_smooth.iloc[i]
        new_state = state

        if state == "Ground":
            if h > 5 and v > 3:
                new_state = "Takeoff"
        elif state == "Takeoff":
            if vr > 0.3 and h > 20:
                new_state = "Climb"
            elif h < 2:
                new_state = "Ground"
        elif state == "Climb":
            if abs(vr) < 0.2 and h > 30:
                new_state = "Cruise"
            elif vr < -0.3:
                new_state = "Descent"
        elif state == "Cruise":
            if vr > 0.5:
                new_state = "Climb"
            elif vr < -0.5:
                new_state = "Descent"
        elif state == "Descent":
            if vr > 0.5:
                new_state = "Climb"
            elif h < 10 and v < 10:
                new_state = "Landing"
        elif state == "Landing":
            if v < 1:
                new_state = "Ground"

        if new_state != state:
            duration = float(times[i] - times[start_idx])
            if duration > 2:
                phases.append({
                    "phase": state,
                    "start": _fmt_time(float(times[start_idx])),
                    "end": _fmt_time(float(times[i])),
                    "duration": _fmt_duration(duration),
                    "duration_seconds": round(duration, 2),
                })
            state = new_state
            start_idx = i

    duration = float(times[-1] - times[start_idx])
    if duration > 2:
        phases.append({
            "phase": state,
            "start": _fmt_time(float(times[start_idx])),
            "end": _fmt_time(float(times[-1])),
            "duration": _fmt_duration(duration),
            "duration_seconds": round(duration, 2),
        })

    return phases


def _detect_altitude_jump_anomalies(
    times: np.ndarray,
    altitudes: np.ndarray,
    times_raw_utc: np.ndarray,
    port: int,
    parser_id: Optional[int],
) -> List[Dict[str, Any]]:
    """IRS altitude 跳变检测：沿用 50 m/s 阈值。

    times 为与飞行阶段一致的「日内秒」偏移序列，用于 dt；times_raw_utc 为解析库原始 UTC Unix 秒，用于展示与深链。
    """
    if times is None or len(times) < 10:
        return []
    if times_raw_utc is None or len(times_raw_utc) != len(times):
        times_raw_utc = times
    alt_arr = np.asarray(altitudes, dtype=float)
    dt = np.diff(times)
    da = np.abs(np.diff(alt_arr))
    out: List[Dict[str, Any]] = []
    for i in range(len(da)):
        if dt[i] > 0 and da[i] / max(float(dt[i]), 0.01) > ALTITUDE_JUMP_THRESHOLD:
            raw_ts = float(times_raw_utc[i + 1])
            # 解析库 timestamp 为 Unix UTC 秒；明显过小则视为非 epoch（不应深链）
            plausible_epoch = np.isfinite(raw_ts) and 946684800 < raw_ts < 4102444800
            row: Dict[str, Any] = {
                "time": _fmt_timestamp_beijing_utc(raw_ts) if plausible_epoch else _fmt_time(float(times[i + 1])),
                "time_seconds": float(times[i + 1]),
                "type": "Altitude Jump",
                "detail": f"Altitude changed {da[i]:.1f}m in {dt[i]:.1f}s",
                "severity": "warning",
                "source": f"IRS port={port}",
                "port": int(port),
                "parser_id": int(parser_id) if parser_id is not None else None,
            }
            if plausible_epoch:
                row["time_utc"] = _fmt_timestamp_utc_iso(raw_ts)
                row["parse_ts"] = raw_ts
            out.append(row)
            if len(out) > 20:
                break
    return out


def _detect_status_anomalies(
    df: pd.DataFrame, time_col: str, port: int, parser_id: Optional[int]
) -> List[Dict[str, Any]]:
    """扫描 IRS *_status_enum 列，统计非 valid 段。时间戳按解析库 UTC Unix 秒展示为北京时间。"""
    out: List[Dict[str, Any]] = []
    status_cols = [c for c in DEFAULT_STATUS_COLS if c in df.columns]
    if not status_cols or time_col not in df.columns:
        return out
    for col in status_cols:
        vals = df[col].astype(str).str.lower()
        # 正常状态大多是 normal/valid/ok；非此即视作异常
        bad_mask = ~vals.isin(["normal", "valid", "ok", "0", "正常"]) & vals.notna() & (vals != "nan")
        if not bad_mask.any():
            continue
        # 按连续段聚合
        groups = (bad_mask != bad_mask.shift()).cumsum()
        bad_segments = df.loc[bad_mask].groupby(groups.loc[bad_mask])
        count = 0
        for _, seg in bad_segments:
            if count >= 5:
                break
            t0 = float(seg[time_col].iloc[0])
            t1 = float(seg[time_col].iloc[-1])
            state = seg[col].iloc[0]
            plausible_epoch = np.isfinite(t0) and 946684800 < t0 < 4102444800
            row: Dict[str, Any] = {
                "time": _fmt_timestamp_beijing_utc(t0) if plausible_epoch else _fmt_time(t0),
                "time_seconds": t0,
                "type": f"IRS {col.replace('_enum', '')} abnormal",
                "detail": f"{col}={state} 持续 {t1 - t0:.1f}s",
                "severity": "warning",
                "source": f"IRS port={port}",
                "port": int(port),
                "parser_id": int(parser_id) if parser_id is not None else None,
            }
            if plausible_epoch:
                row["time_utc"] = _fmt_timestamp_utc_iso(t0)
                row["parse_ts"] = t0
            out.append(row)
            count += 1
        if len(out) > 30:
            break
    return out


def _generate_narrative(result: Dict[str, Any]) -> str:
    """移植 flight_data_webapp/app.py:generate_narrative，替换电池段为姿态段。"""
    info = result.get("flight_info", {})
    profile = result.get("flight_profile", {})
    phases = result.get("phases", [])
    attitude = result.get("attitude", {})
    anomalies = result.get("anomalies", [])

    lines: List[str] = []

    lines.append(
        f"本架次数据记录时间为 {info.get('start_time', '?')} 至 {info.get('end_time', '?')}，"
        f"总时长 {info.get('duration', '?')}，共包含 {info.get('dataset_count', 0)} 个解析端口。"
    )

    if profile.get("start_position"):
        lines.append(f"起始位置 {profile['start_position']}，终止位置 {profile.get('end_position', '?')}。")

    has_flight = info.get("has_flight", False)
    alt_range = profile.get("altitude_range_m", 0) or 0
    if not has_flight:
        lines.append(
            f"本架次高度变化仅 {alt_range:.1f}m（{profile.get('min_altitude_m', '?')}m ~ "
            f"{profile.get('max_altitude_m', '?')}m），未检测到明显的起飞/着陆过程，判断为地面运行/滑行数据。"
        )
    else:
        lines.append(f"最大高度 {profile.get('max_altitude_m', '?')}m，高度变化范围 {alt_range:.1f}m。")
        if profile.get("max_ground_speed") is not None:
            lines.append(f"最大地速 {profile['max_ground_speed']} m/s。")
        if profile.get("max_airspeed") is not None:
            extra = f"，最大马赫数 {profile['max_mach']}" if profile.get("max_mach") is not None else ""
            lines.append(f"最大空速 {profile['max_airspeed']} m/s{extra}。")

    if phases:
        phase_desc = [f"{p['phase']}({p['start']}~{p['end']}, {p['duration']})" for p in phases]
        lines.append("飞行阶段：" + " → ".join(phase_desc) + "。")

    # Attitude summary (替代 CSV 平台的电池段)
    if attitude:
        def fmt_range(name: str, unit: str = "°") -> Optional[str]:
            d = attitude.get(name)
            if not d:
                return None
            return f"{name} 范围 {d.get('min', '?')}{unit} ~ {d.get('max', '?')}{unit}（均值 {d.get('mean', '?')}{unit}）"

        parts = [s for s in (
            fmt_range("pitch"),
            fmt_range("roll"),
            fmt_range("heading"),
        ) if s]
        if parts:
            lines.append("姿态：" + "；".join(parts) + "。")

    critical = [a for a in anomalies if a.get("severity") == "critical"]
    warnings = [a for a in anomalies if a.get("severity") == "warning"]
    if critical:
        lines.append(
            f"发现 {len(critical)} 个严重异常（Critical），涉及 "
            + "、".join(sorted({a['type'] for a in critical}))
            + "，需重点关注。"
        )
    if warnings:
        lines.append(
            f"发现 {len(warnings)} 个告警（Warning），涉及 "
            + "、".join(sorted({a['type'] for a in warnings}))
            + "。"
        )
    if not critical and not warnings:
        lines.append("未发现明显物理异常，本架次总览数据质量良好；详见底部事件分析总结。")

    return "\n".join(lines)


def _quality_badge(anomalies: List[Dict[str, Any]]) -> str:
    critical = sum(1 for a in anomalies if a.get("severity") == "critical")
    warning = sum(1 for a in anomalies if a.get("severity") == "warning")
    if critical > 0:
        return "Critical"
    if warning > 5:
        return "Warning"
    if warning > 0:
        return "Minor Issues"
    return "Good"


# ──────────────────────────── Overview 主入口 ────────────────────────────

def _attitude_stats(series: pd.Series) -> Optional[Dict[str, float]]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return {
        "min": round(float(s.min()), 2),
        "max": round(float(s.max()), 2),
        "mean": round(float(s.mean()), 2),
        "count": int(s.size),
    }


def _read_parquet_safe(path: Path, columns: Optional[List[str]] = None) -> Optional[pd.DataFrame]:
    try:
        if columns:
            # pandas.read_parquet 支持 columns 过滤
            return pd.read_parquet(path, columns=columns)
        return pd.read_parquet(path)
    except Exception:
        return None


async def build_overview(db: AsyncSession, parse_task_id: int) -> Dict[str, Any]:
    """聚合解析任务级总览。"""
    pt = (await db.execute(select(ParseTask).where(ParseTask.id == parse_task_id))).scalar_one_or_none()
    if not pt:
        return {"error": "解析任务不存在"}

    results: List[ParseResult] = (
        await db.execute(select(ParseResult).where(ParseResult.task_id == parse_task_id))
    ).scalars().all()

    # 时间范围 + 端口数
    t_min_dt = min((r.time_start for r in results if r.time_start), default=None)
    t_max_dt = max((r.time_end for r in results if r.time_end), default=None)
    t_min = _dt_to_seconds(t_min_dt)
    t_max = _dt_to_seconds(t_max_dt)
    duration = (t_max - t_min) if (t_min is not None and t_max is not None) else None

    flight_info: Dict[str, Any] = {
        "parse_task_id": parse_task_id,
        "parse_task_name": pt.display_name or pt.filename,
        "dataset_count": len(results),
        "start_time": _fmt_time(t_min),
        "end_time": _fmt_time(t_max),
        "start_time_iso": _dt_to_iso(t_min_dt),
        "end_time_iso": _dt_to_iso(t_max_dt),
        "duration": _fmt_duration(duration),
        "duration_seconds": round(duration, 2) if duration is not None else None,
    }

    # IRS 主端口识别
    irs_candidates = [r for r in results if _is_irs_result(r)]
    irs_primary = _pick_primary(irs_candidates)
    adc_candidates = [r for r in results if _is_adc_result(r)]
    adc_primary = _pick_primary(adc_candidates)

    profile: Dict[str, Any] = {}
    attitude: Dict[str, Any] = {}
    anomalies: List[Dict[str, Any]] = []
    phases: List[Dict[str, Any]] = []
    trajectory: Optional[Dict[str, Any]] = None
    attitude_series: Optional[Dict[str, Any]] = None
    primary_irs_info: Optional[Dict[str, Any]] = None

    if irs_primary:
        path = _resolve_parquet_path(irs_primary.result_file, parse_task_id, irs_primary.port_number)
        if path:
            df = _read_parquet_safe(path)
            if df is not None and not df.empty:
                cols = list(df.columns)
                time_col = "timestamp" if "timestamp" in cols else None
                lat_col = _latitude_col(cols)
                lon_col = _longitude_col(cols)
                alt_col = _altitude_col(cols)
                spd_col = _groundspeed_col(cols)
                east_col = _east_velocity_col(cols)
                north_col = _north_velocity_col(cols)
                pitch_col = _pitch_col(cols)
                roll_col = _roll_col(cols)
                hdg_col = _heading_col(cols)

                # CSV 平台的 zero_filter（lat=0 视为未初始化）
                if lat_col and lon_col:
                    mask = (pd.to_numeric(df[lat_col], errors="coerce") != 0) & df[lat_col].notna()
                    df_filtered = df.loc[mask].reset_index(drop=True)
                else:
                    df_filtered = df

                # 转时间 → 秒（"本地一天内的秒数"），与 _dt_to_seconds(time_start) 口径一致，
                # 使 phases/anomalies 的 HH:MM:SS 与 flight_info.start_time/end_time 同基准。
                if time_col and time_col in df_filtered.columns:
                    t_epoch = pd.to_numeric(df_filtered[time_col], errors="coerce").to_numpy(dtype=float)
                    if np.isfinite(t_epoch).any():
                        first_valid = float(t_epoch[np.isfinite(t_epoch)][0])
                        try:
                            first_local = _dt_to_seconds(datetime.fromtimestamp(first_valid))
                            offset = (first_local or 0.0) - first_valid
                            t_arr = t_epoch + offset
                        except (OverflowError, OSError, ValueError):
                            t_arr = t_epoch
                    else:
                        t_arr = t_epoch
                else:
                    t_arr = np.arange(len(df_filtered), dtype=float)

                # 高度统计
                if alt_col and alt_col in df_filtered.columns:
                    a = pd.to_numeric(df_filtered[alt_col], errors="coerce").dropna()
                    if not a.empty:
                        profile["max_altitude_m"] = round(float(a.max()), 1)
                        profile["min_altitude_m"] = round(float(a.min()), 1)
                        profile["altitude_range_m"] = round(float(a.max() - a.min()), 1)

                # 地速统计：优先显式列，否则用 east/north 合成
                gs_values: Optional[np.ndarray] = None
                if spd_col and spd_col in df_filtered.columns:
                    v = pd.to_numeric(df_filtered[spd_col], errors="coerce")
                    if v.notna().any():
                        gs_values = v.to_numpy(dtype=float)
                if gs_values is None and east_col and north_col:
                    ve = pd.to_numeric(df_filtered[east_col], errors="coerce").to_numpy(dtype=float)
                    vn = pd.to_numeric(df_filtered[north_col], errors="coerce").to_numpy(dtype=float)
                    if ve.size and vn.size:
                        gs_values = np.hypot(ve, vn)
                if gs_values is not None and np.isfinite(gs_values).any():
                    profile["max_ground_speed"] = round(float(np.nanmax(gs_values)), 1)

                # 起止位置
                if lat_col and lon_col and not df_filtered.empty:
                    try:
                        la0 = float(df_filtered[lat_col].iloc[0])
                        lo0 = float(df_filtered[lon_col].iloc[0])
                        la1 = float(df_filtered[lat_col].iloc[-1])
                        lo1 = float(df_filtered[lon_col].iloc[-1])
                        profile["start_position"] = f"{la0:.6f}N, {lo0:.6f}E"
                        profile["end_position"] = f"{la1:.6f}N, {lo1:.6f}E"
                    except Exception:
                        pass

                # 姿态统计
                if pitch_col:
                    st = _attitude_stats(df_filtered[pitch_col])
                    if st:
                        attitude["pitch"] = st
                if roll_col:
                    st = _attitude_stats(df_filtered[roll_col])
                    if st:
                        attitude["roll"] = st
                if hdg_col:
                    st = _attitude_stats(df_filtered[hdg_col])
                    if st:
                        attitude["heading"] = st

                # 飞行阶段：需要时间+高度
                if alt_col and len(t_arr) >= 10:
                    alt_arr = pd.to_numeric(df_filtered[alt_col], errors="coerce").to_numpy(dtype=float)
                    # 取 time 与 alt 同时有效的子集
                    valid_mask = np.isfinite(t_arr) & np.isfinite(alt_arr)
                    t_valid = t_arr[valid_mask]
                    alt_valid = alt_arr[valid_mask]
                    spd_valid = None
                    if gs_values is not None and gs_values.size == len(t_arr):
                        s_valid = gs_values[valid_mask]
                        if np.isfinite(s_valid).any():
                            spd_valid = s_valid
                    if len(t_valid) >= 10:
                        phases = _detect_flight_phases(t_valid, alt_valid, spd_valid)
                        t_raw_valid = t_epoch[valid_mask]
                        anomalies.extend(
                            _detect_altitude_jump_anomalies(
                                t_valid,
                                alt_valid,
                                t_raw_valid,
                                irs_primary.port_number,
                                irs_primary.parser_profile_id,
                            )
                        )

                if time_col:
                    anomalies.extend(
                        _detect_status_anomalies(
                            df_filtered,
                            time_col,
                            irs_primary.port_number,
                            irs_primary.parser_profile_id,
                        )
                    )

                # 轨迹降采样（与 CSV 平台 3000 点对齐）
                if lat_col and lon_col and len(df_filtered) > 0:
                    idxs = _downsample_indices(len(df_filtered))
                    sub = df_filtered.iloc[idxs]
                    lat_s = pd.to_numeric(sub[lat_col], errors="coerce").to_numpy(dtype=float)
                    lon_s = pd.to_numeric(sub[lon_col], errors="coerce").to_numpy(dtype=float)
                    t_s = t_arr[idxs] if len(t_arr) == len(df_filtered) else np.arange(len(sub), dtype=float)
                    alt_s = pd.to_numeric(sub[alt_col], errors="coerce").to_numpy(dtype=float) if alt_col else None
                    spd_s = (gs_values[idxs] if gs_values is not None and gs_values.size == len(df_filtered) else None)
                    trajectory = {
                        "time": [round(float(x), 2) for x in t_s],
                        "lat": [round(float(x), 6) for x in lat_s],
                        "lon": [round(float(x), 6) for x in lon_s],
                    }
                    if alt_s is not None:
                        trajectory["alt"] = [round(float(x), 2) for x in alt_s]
                    if spd_s is not None:
                        trajectory["speed"] = [round(float(x), 2) for x in spd_s]
                    trajectory["source"] = f"IRS port={irs_primary.port_number}"

                # 姿态时序降采样
                if any([pitch_col, roll_col, hdg_col]) and len(df_filtered) > 0:
                    idxs = _downsample_indices(len(df_filtered))
                    sub = df_filtered.iloc[idxs]
                    t_s = t_arr[idxs] if len(t_arr) == len(df_filtered) else np.arange(len(sub), dtype=float)
                    attitude_series = {
                        "time": [round(float(x), 3) for x in t_s],
                    }
                    # 附带 UTC 原始 epoch 秒；前端以此渲染北京时间 HH:MM:SS
                    if time_col and time_col in df_filtered.columns and len(t_epoch) == len(df_filtered):
                        t_epoch_s = t_epoch[idxs]
                        attitude_series["time_epoch"] = [
                            None if not np.isfinite(v) else round(float(v), 3) for v in t_epoch_s
                        ]
                    for label, col in (("pitch", pitch_col), ("roll", roll_col), ("yaw", hdg_col)):
                        if col and col in sub.columns:
                            vals = pd.to_numeric(sub[col], errors="coerce").to_numpy(dtype=float)
                            attitude_series[label] = [
                                None if not np.isfinite(v) else round(float(v), 3) for v in vals
                            ]

        primary_irs_info = {
            "port": int(irs_primary.port_number),
            "parser_id": int(irs_primary.parser_profile_id) if irs_primary.parser_profile_id else None,
            "parser_name": irs_primary.parser_profile_name,
            "source_device": irs_primary.source_device,
            "record_count": int(irs_primary.record_count or 0),
        }

    # ADC 空速/马赫
    if adc_primary:
        path = _resolve_parquet_path(adc_primary.result_file, parse_task_id, adc_primary.port_number)
        if path:
            df = _read_parquet_safe(path)
            if df is not None and not df.empty:
                cols = list(df.columns)
                asc = _airspeed_col(cols)
                mc = _mach_col(cols)
                if asc:
                    v = pd.to_numeric(df[asc], errors="coerce")
                    v = v[v > 0]
                    if not v.empty:
                        profile["max_airspeed"] = round(float(v.max()), 1)
                if mc:
                    v = pd.to_numeric(df[mc], errors="coerce")
                    v = v[v > 0]
                    if not v.empty:
                        profile["max_mach"] = round(float(v.max()), 4)

    flight_info["has_flight"] = (profile.get("altitude_range_m") or 0) > 20
    if not flight_info["has_flight"]:
        flight_info["note"] = "未检测到显著高度变化，判断为地面/滑行数据"

    result: Dict[str, Any] = {
        "flight_info": flight_info,
        "flight_profile": profile,
        "attitude": attitude,
        "phases": phases,
        "anomalies": anomalies,
        "quality": _quality_badge(anomalies),
        "primary_irs": primary_irs_info,
        "primary_adc": (
            {
                "port": int(adc_primary.port_number),
                "parser_id": int(adc_primary.parser_profile_id) if adc_primary.parser_profile_id else None,
                "parser_name": adc_primary.parser_profile_name,
            } if adc_primary else None
        ),
        "trajectory": trajectory,
        "attitude_series": attitude_series,
        "ports": [
            {
                "port": int(r.port_number),
                "parser_name": r.parser_profile_name,
                "parser_id": int(r.parser_profile_id) if r.parser_profile_id else None,
                "source_device": r.source_device,
                "message_name": r.message_name,
                "record_count": int(r.record_count or 0),
                "is_irs": _is_irs_result(r),
                "is_adc": _is_adc_result(r),
            }
            for r in results
        ],
    }
    result["narrative"] = _generate_narrative(result)
    return result


# ──────────────────────────── Events Summary ────────────────────────────

def _link_filter(model_task_cls, parse_task_ids: List[int], shared_file_paths: List[str]):
    """构造「分析任务 ↔ 架次」关联过滤。

    架次归属严格只走 *平台共享数据*：

    - 解析任务路径：分析任务的 ``parse_task_id`` 命中本架次共享文件衍生出的解析任务；
    - 共享 pcap 路径：分析任务的 ``pcap_file_path`` 直接等于本架次某个共享文件路径
      （由 ``/standalone/from-shared`` 创建的 standalone 任务即落在这里）。

    本地上传的 standalone 任务（``pcap_file_path`` 落在 ``uploads/...`` 目录）不会
    被任何架次的共享路径集合命中，因此天然不归入任何架次，符合"本地上传不绑定架次"
    的产品口径。

    任一集合为空时只用另一个；都为空时返回 ``None`` 表示"不可能命中"。
    """
    clauses = []
    if parse_task_ids:
        clauses.append(model_task_cls.parse_task_id.in_(parse_task_ids))
    if shared_file_paths and hasattr(model_task_cls, "pcap_file_path"):
        clauses.append(model_task_cls.pcap_file_path.in_(shared_file_paths))
    if not clauses:
        return None
    return or_(*clauses)


def _serialize_event_row(e) -> Dict[str, Any]:
    """把 FMS/FCC timeline 行序列化为前端可消费的字典。

    保持和原 ``top_events`` 字段名兼容（``ts`` / ``parse_ts`` / ``port`` /
    ``title`` / ``severity`` / ``time_str`` / ``device``），并附带 ``event_type``
    便于前端按类型上色。
    """
    return {
        "ts": _safe_float(e.timestamp),
        "parse_ts": _safe_float(e.timestamp),
        "port": e.port,
        "title": e.event_name or e.event_type or "事件",
        "severity": "info",
        "time_str": e.time_str,
        "device": e.device,
        "event_type": e.event_type,
        "description": getattr(e, "event_description", None),
    }


def _link_source(task, parse_task_ids: List[int]) -> str:
    """识别该分析任务是经由解析任务关联，还是 standalone 直接选了共享数据。"""
    pid = getattr(task, "parse_task_id", None)
    if pid and parse_task_ids and pid in parse_task_ids:
        return "parse_task"
    if getattr(task, "pcap_file_path", None):
        return "shared_pcap"
    return "unknown"


async def _summarize_fms(
    db: AsyncSession,
    parse_task_ids: List[int],
    file_paths: List[str],
) -> Dict[str, Any]:
    cond = _link_filter(FmsEventAnalysisTask, parse_task_ids, file_paths)
    if cond is None:
        return {"module": "fms", "name": "飞管事件分析", "task_id": None, "status": "not_run"}

    task = (
        await db.execute(
            select(FmsEventAnalysisTask)
            .where(cond)
            .order_by(FmsEventAnalysisTask.id.desc())
        )
    ).scalars().first()
    if not task:
        return {"module": "fms", "name": "飞管事件分析", "task_id": None, "status": "not_run"}

    timeline_rows = (
        await db.execute(
            select(FmsEventTimelineEvent)
            .where(FmsEventTimelineEvent.analysis_task_id == task.id)
            .order_by(FmsEventTimelineEvent.timestamp.asc())
        )
    ).scalars().all()
    check_rows = (
        await db.execute(
            select(FmsEventCheckResult)
            .where(FmsEventCheckResult.analysis_task_id == task.id)
            .order_by(FmsEventCheckResult.sequence.asc())
        )
    ).scalars().all()

    timeline_events = [_serialize_event_row(e) for e in timeline_rows]
    narrative = build_fms_narrative(task, list(timeline_rows), list(check_rows))

    return {
        "module": "fms",
        "name": "飞管事件分析",
        "task_id": task.id,
        "status": task.status or "pending",
        "progress": task.progress or 0,
        "counts": {
            "total": task.total_checks or 0,
            "pass": task.passed_checks or 0,
            "fail": task.failed_checks or 0,
        },
        "top_events": timeline_events[:5],
        "timeline_events": timeline_events,
        "summary_text": narrative["summary_text"],
        "timeline_narrative": narrative["timeline_narrative"],
        "summary_tags": narrative["summary_tags"],
        "detail_route": f"/fms-event-analysis/task/{task.id}",
        "linked_parse_task_id": task.parse_task_id,
        "linked_pcap_filename": task.pcap_filename,
        "link_source": _link_source(task, parse_task_ids),
    }


async def _summarize_fcc(
    db: AsyncSession,
    parse_task_ids: List[int],
    file_paths: List[str],
) -> Dict[str, Any]:
    cond = _link_filter(FccEventAnalysisTask, parse_task_ids, file_paths)
    if cond is None:
        return {"module": "fcc", "name": "飞控事件分析", "task_id": None, "status": "not_run"}

    task = (
        await db.execute(
            select(FccEventAnalysisTask)
            .where(cond)
            .order_by(FccEventAnalysisTask.id.desc())
        )
    ).scalars().first()
    if not task:
        return {"module": "fcc", "name": "飞控事件分析", "task_id": None, "status": "not_run"}

    timeline_rows = (
        await db.execute(
            select(FccEventTimelineEvent)
            .where(FccEventTimelineEvent.analysis_task_id == task.id)
            .order_by(FccEventTimelineEvent.timestamp.asc())
        )
    ).scalars().all()
    check_rows = (
        await db.execute(
            select(FccEventCheckResult)
            .where(FccEventCheckResult.analysis_task_id == task.id)
            .order_by(FccEventCheckResult.sequence.asc())
        )
    ).scalars().all()

    timeline_events = [_serialize_event_row(e) for e in timeline_rows]
    narrative = build_fcc_narrative(task, list(timeline_rows), list(check_rows))

    detected = sum(1 for c in check_rows if (c.overall_result or "") == "detected")
    not_detected = sum(1 for c in check_rows if (c.overall_result or "") == "not_detected")
    na = sum(1 for c in check_rows if (c.overall_result or "") == "na")

    return {
        "module": "fcc",
        "name": "飞控事件分析",
        "task_id": task.id,
        "status": task.status or "pending",
        "progress": task.progress or 0,
        # FCC 用 detected/not_detected/na 三值；保留 total 让前端能对照
        "counts": {
            "total": task.total_checks or len(check_rows),
            "detected": detected,
            "not_detected": not_detected,
            "na": na,
        },
        "top_events": timeline_events[:5],
        "timeline_events": timeline_events,
        "summary_text": narrative["summary_text"],
        "timeline_narrative": narrative["timeline_narrative"],
        "summary_tags": narrative["summary_tags"],
        "detail_route": f"/fcc-event-analysis/task/{task.id}",
        "linked_parse_task_id": task.parse_task_id,
        "linked_pcap_filename": task.pcap_filename,
        "link_source": _link_source(task, parse_task_ids),
    }


async def _summarize_auto_flight(
    db: AsyncSession,
    parse_task_ids: List[int],
    file_paths: List[str],
) -> Dict[str, Any]:
    cond = _link_filter(AutoFlightAnalysisTask, parse_task_ids, file_paths)
    if cond is None:
        return {"module": "auto_flight", "name": "自动飞行性能分析", "task_id": None, "status": "not_run"}

    task = (
        await db.execute(
            select(AutoFlightAnalysisTask)
            .where(cond)
            .order_by(AutoFlightAnalysisTask.id.desc())
        )
    ).scalars().first()
    if not task:
        return {"module": "auto_flight", "name": "自动飞行性能分析", "task_id": None, "status": "not_run"}

    touch_rows = (
        await db.execute(
            select(TouchdownAnalysisResult)
            .where(TouchdownAnalysisResult.analysis_task_id == task.id)
            .order_by(TouchdownAnalysisResult.sequence.asc())
        )
    ).scalars().all()
    steady_rows = (
        await db.execute(
            select(SteadyStateAnalysisResult)
            .where(SteadyStateAnalysisResult.analysis_task_id == task.id)
            .order_by(SteadyStateAnalysisResult.sequence.asc())
        )
    ).scalars().all()

    timeline_events: List[Dict[str, Any]] = []
    for t in touch_rows:
        timeline_events.append({
            "ts": _safe_float(t.touchdown_ts),
            "parse_ts": _safe_float(t.touchdown_ts),
            "port": None,
            "title": f"触地 #{t.sequence} · {t.rating or 'normal'}",
            "severity": "warning" if (t.rating or "") not in ("normal", "") else "info",
            "time_str": t.touchdown_time,
            "event_type": "touchdown",
            "description": t.summary,
        })
    for s in steady_rows:
        timeline_events.append({
            "ts": _safe_float(s.start_ts),
            "parse_ts": _safe_float(s.start_ts),
            "port": None,
            "title": f"稳态 #{s.sequence} {s.mode_label or ''} · {s.rating or 'normal'}",
            "severity": "warning" if (s.rating or "") not in ("normal", "") else "info",
            "time_str": s.start_time,
            "event_type": "steady",
            "description": s.summary,
        })
    timeline_events.sort(key=lambda x: x.get("ts") or 0.0)
    top_events = timeline_events[:5]

    narrative = build_auto_flight_narrative(task, list(touch_rows), list(steady_rows))

    return {
        "module": "auto_flight",
        "name": "自动飞行性能分析",
        "task_id": task.id,
        "status": task.status or "pending",
        "progress": task.progress or 0,
        "counts": {
            "touchdown": task.touchdown_count or 0,
            "steady": task.steady_count or 0,
        },
        "top_events": top_events,
        "timeline_events": timeline_events,
        "summary_text": narrative["summary_text"],
        "timeline_narrative": narrative["timeline_narrative"],
        "summary_tags": narrative["summary_tags"],
        "detail_route": f"/auto-flight-analysis/task/{task.id}",
        "linked_parse_task_id": task.parse_task_id,
        "linked_pcap_filename": task.pcap_filename,
        "link_source": _link_source(task, parse_task_ids),
    }


async def _summarize_compare(
    db: AsyncSession,
    file_paths: List[str],
) -> Dict[str, Any]:
    """比对任务通过 file_path_1 / file_path_2 与架次文件路径匹配。"""
    if not file_paths:
        return {"module": "compare", "name": "TSN 异常检查（双交换机比对）", "task_id": None, "status": "not_run"}

    task = (
        await db.execute(
            select(CompareTask)
            .where(or_(
                CompareTask.file_path_1.in_(file_paths),
                CompareTask.file_path_2.in_(file_paths),
            ))
            .order_by(CompareTask.id.desc())
        )
    ).scalars().first()
    if not task:
        return {"module": "compare", "name": "TSN 异常检查（双交换机比对）", "task_id": None, "status": "not_run"}

    port_rows = (
        await db.execute(
            select(ComparePortResult)
            .where(ComparePortResult.compare_task_id == task.id)
        )
    ).scalars().all()
    timing_rows = (
        await db.execute(
            select(ComparePortTimingResult)
            .where(ComparePortTimingResult.compare_task_id == task.id)
        )
    ).scalars().all()
    # 丢包段按端口/侧聚合，避免拉数千行明细到内存
    gap_count_rows = (
        await db.execute(
            select(
                CompareGapRecord.port_number,
                CompareGapRecord.switch_index,
                func.count(CompareGapRecord.id).label("gap_count"),
                func.sum(CompareGapRecord.estimated_missing_packets).label("missing_pkts"),
            )
            .where(CompareGapRecord.compare_task_id == task.id)
            .group_by(CompareGapRecord.port_number, CompareGapRecord.switch_index)
        )
    ).all()

    narrative = build_compare_narrative(
        task,
        list(port_rows),
        list(timing_rows),
        [
            {
                "port_number": r[0],
                "switch_index": r[1],
                "gap_count": int(r[2] or 0),
                "missing_pkts": int(r[3] or 0),
            }
            for r in gap_count_rows
        ],
    )

    # compare 没有时间线，把"问题端口"作为 timeline_events 给前端折叠展示
    problem_events: List[Dict[str, Any]] = []
    for p in port_rows:
        if (p.result or "").lower() in ("warning", "fail"):
            problem_events.append({
                "ts": None,
                "parse_ts": None,
                "port": p.port_number,
                "title": f"端口 {p.port_number} · {p.message_name or p.source_device or ''}",
                "severity": "error" if (p.result or "").lower() == "fail" else "warning",
                "time_str": None,
                "event_type": "port_issue",
                "description": p.detail,
            })
    for t in timing_rows:
        if (t.result or "").lower() in ("warning", "fail"):
            problem_events.append({
                "ts": None,
                "parse_ts": None,
                "port": t.port_number,
                "title": (
                    f"端口 {t.port_number} 交换机{t.switch_index} 周期"
                    f"{'失败' if (t.result or '').lower() == 'fail' else '告警'}"
                ),
                "severity": "error" if (t.result or "").lower() == "fail" else "warning",
                "time_str": None,
                "event_type": "timing_issue",
                "description": t.detail,
            })

    return {
        "module": "compare",
        "name": "TSN 异常检查（双交换机比对）",
        "task_id": task.id,
        "status": task.status or "pending",
        "progress": task.progress or 0,
        "counts": {
            "missing_ports": task.missing_count or 0,
            "ports_with_gaps": task.ports_with_gaps or 0,
            "timing_fail": task.timing_fail_count or 0,
            "timing_warning": task.timing_warning_count or 0,
        },
        "top_events": problem_events[:5],
        "timeline_events": problem_events,
        "overall_result": task.overall_result,
        "summary_text": narrative["summary_text"],
        "timeline_narrative": narrative["timeline_narrative"],
        "summary_tags": narrative["summary_tags"],
        "detail_route": f"/compare/{task.id}",
    }


async def _collect_sortie_links(
    db: AsyncSession, sortie_id: int
) -> Tuple[List[str], List[int]]:
    """汇总该架次绑定的「平台共享数据」文件路径，以及由这些文件衍生出的解析任务 id。

    架次只通过 ``SharedTsnFile.sortie_id`` 与共享数据建立归属，因此凡是
    ``ParseTask.file_path`` / ``XxxTask.pcap_file_path`` 命中此处返回的 ``file_paths``
    才被视为"属于本架次"。本地直传 pcap 的 standalone 任务不会被命中。
    """
    files = (
        await db.execute(
            select(SharedTsnFile.file_path).where(SharedTsnFile.sortie_id == sortie_id)
        )
    ).scalars().all()
    file_paths = [p for p in files if p]
    parse_task_ids: List[int] = []
    if file_paths:
        rows = (
            await db.execute(
                select(ParseTask.id).where(ParseTask.file_path.in_(file_paths))
            )
        ).scalars().all()
        parse_task_ids = [int(x) for x in rows if x is not None]
    return file_paths, parse_task_ids


async def build_events_summary(
    db: AsyncSession,
    sortie_id: int,
    parse_task_id: Optional[int] = None,
) -> Dict[str, Any]:
    """聚合一个架次相关的四类专项分析。

    关联口径（**严格只通过平台共享数据建立归属**）：

    1. 取出架次绑定的全部 ``SharedTsnFile.file_path``；
    2. 解析任务侧：``ParseTask.file_path`` 命中上述路径的，归入该架次；
       任一专项分析挂在这些 ``parse_task_id`` 上即视为属于该架次。
    3. Standalone 共享侧：``XxxAnalysisTask.pcap_file_path`` 直接命中上述路径的，
       同样归入该架次（即 ``/standalone/from-shared`` 那条路径）。

    本地直接上传 pcap 的 standalone 任务（``pcap_file_path`` 在 ``uploads/...``
    目录下），既不命中架次共享路径，也没有 parse_task 关联，因此不属于任何架次。

    ``parse_task_id`` 仍可作为可选筛选项，用来把视图收窄到「仅看某个解析任务下发起
    的分析」；不传则按整架次自动聚合。共享 pcap 兜底始终按整架次匹配，避免遗漏
    standalone-from-shared 入口的分析。
    """
    file_paths, sortie_parse_task_ids = await _collect_sortie_links(db, sortie_id)
    if parse_task_id is not None:
        narrowed_parse_task_ids = [parse_task_id]
    else:
        narrowed_parse_task_ids = sortie_parse_task_ids

    fms = await _summarize_fms(db, narrowed_parse_task_ids, file_paths)
    fcc = await _summarize_fcc(db, narrowed_parse_task_ids, file_paths)
    af = await _summarize_auto_flight(db, narrowed_parse_task_ids, file_paths)
    cmp_ = await _summarize_compare(db, file_paths)

    return {
        "sortie_id": sortie_id,
        "parse_task_id": parse_task_id,
        "linked_parse_task_ids": sortie_parse_task_ids,
        "linked_file_count": len(file_paths),
        "modules": [fms, fcc, af, cmp_],
    }


# ──────────────────────────── Matched tasks ────────────────────────────

async def list_matched_tasks(db: AsyncSession, sortie_id: int) -> Dict[str, Any]:
    """按架次反查候选解析任务及其事件分析状态。"""
    # 1. 取架次文件路径
    files = (
        await db.execute(
            select(SharedTsnFile).where(SharedTsnFile.sortie_id == sortie_id)
        )
    ).scalars().all()
    file_paths = [f.file_path for f in files if f.file_path]

    # 2. 反查 parse_tasks（若该架次有文件，优先按 file_path 匹配；否则退化为空列表）
    parse_tasks: List[ParseTask] = []
    if file_paths:
        q = await db.execute(
            select(ParseTask).where(ParseTask.file_path.in_(file_paths))
            .order_by(ParseTask.id.desc())
        )
        parse_tasks = list(q.scalars().all())

    # 3. 逐个任务挂上各类分析 id/status
    out_tasks: List[Dict[str, Any]] = []
    for pt in parse_tasks:
        fms_task = (
            await db.execute(
                select(FmsEventAnalysisTask.id, FmsEventAnalysisTask.status)
                .where(FmsEventAnalysisTask.parse_task_id == pt.id)
                .order_by(FmsEventAnalysisTask.id.desc()).limit(1)
            )
        ).first()
        fcc_task = (
            await db.execute(
                select(FccEventAnalysisTask.id, FccEventAnalysisTask.status)
                .where(FccEventAnalysisTask.parse_task_id == pt.id)
                .order_by(FccEventAnalysisTask.id.desc()).limit(1)
            )
        ).first()
        af_task = (
            await db.execute(
                select(AutoFlightAnalysisTask.id, AutoFlightAnalysisTask.status)
                .where(AutoFlightAnalysisTask.parse_task_id == pt.id)
                .order_by(AutoFlightAnalysisTask.id.desc()).limit(1)
            )
        ).first()

        def _pack(row):
            if not row:
                return None
            return {"task_id": int(row[0]), "status": row[1] or "pending"}

        out_tasks.append({
            "parse_task_id": pt.id,
            "filename": pt.display_name or pt.filename,
            "status": pt.status,
            "file_path": pt.file_path,
            "created_at": _dt_to_iso(pt.created_at),
            "completed_at": _dt_to_iso(pt.completed_at),
            "analyses": {
                "fms": _pack(fms_task),
                "fcc": _pack(fcc_task),
                "auto_flight": _pack(af_task),
            },
        })

    return {
        "sortie_id": sortie_id,
        "matched_file_paths": file_paths,
        "parse_tasks": out_tasks,
    }
