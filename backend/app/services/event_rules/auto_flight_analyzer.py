# -*- coding: utf-8 -*-
"""
自动飞行性能分析核心引擎

输出两类分析：
1) 触底分析（垂直速度 + 垂直加速度 + 三机一致性）
2) 稳态误差分析（高度/水平/速度偏差）
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List
import math

import pandas as pd


@dataclass
class TouchdownResult:
    sequence: int
    touchdown_ts: float
    touchdown_time: str
    irs1_vz: float | None
    irs2_vz: float | None
    irs3_vz: float | None
    vz_spread: float | None
    irs1_az_peak: float | None
    irs2_az_peak: float | None
    irs3_az_peak: float | None
    az_peak_spread: float | None
    rating: str
    summary: str
    chart_data: Dict[str, Any]


@dataclass
class SteadyStateResult:
    sequence: int
    start_ts: float
    end_ts: float
    start_time: str
    end_time: str
    duration_s: float
    mode_label: str
    alt_bias: float | None
    alt_rms: float | None
    alt_max_abs: float | None
    lat_bias: float | None
    lat_rms: float | None
    lat_max_abs: float | None
    spd_bias: float | None
    spd_rms: float | None
    spd_max_abs: float | None
    rating: str
    summary: str
    chart_data: Dict[str, Any]


def _fmt_ts(ts: float) -> str:
    try:
        return pd.to_datetime(ts, unit="s").strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except Exception:
        return str(ts)


def _safe_float(v: Any) -> float | None:
    try:
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    except Exception:
        return None


def _rms(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float((vals.pow(2).mean()) ** 0.5)


def _bias(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.mean())


def _max_abs(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.abs().max())


class AutoFlightAnalyzer:
    """自动飞行性能分析。"""

    def __init__(
        self,
        touchdown_pre_sec: float = 3.0,
        touchdown_post_sec: float = 2.0,
        steady_min_sec: float = 20.0,
    ):
        self.touchdown_pre_sec = touchdown_pre_sec
        self.touchdown_post_sec = touchdown_post_sec
        self.steady_min_sec = steady_min_sec

    def analyze(
        self,
        auto_df: pd.DataFrame,
        irs_by_name: Dict[str, pd.DataFrame],
    ) -> Dict[str, Any]:
        work = auto_df.copy()
        if work.empty or "timestamp" not in work.columns:
            return {
                "summary": {
                    "touchdown_count": 0,
                    "steady_count": 0,
                },
                "touchdowns": [],
                "steady_states": [],
            }

        work = work.sort_values("timestamp").reset_index(drop=True)
        touchdowns = self._analyze_touchdowns(work, irs_by_name)
        steady = self._analyze_steady_states(work)
        return {
            "summary": {
                "touchdown_count": len(touchdowns),
                "steady_count": len(steady),
            },
            "touchdowns": [asdict(x) for x in touchdowns],
            "steady_states": [asdict(x) for x in steady],
        }

    def _analyze_touchdowns(
        self,
        auto_df: pd.DataFrame,
        irs_by_name: Dict[str, pd.DataFrame],
    ) -> List[TouchdownResult]:
        if "air_ground" not in auto_df.columns:
            return []
        ag = pd.to_numeric(auto_df["air_ground"], errors="coerce")
        prev = ag.shift(1).fillna(ag)
        td_rows = auto_df[(prev == 0) & (ag == 1)]
        if td_rows.empty:
            return []

        results: List[TouchdownResult] = []
        for i, row in enumerate(td_rows.itertuples(index=False), start=1):
            t0 = float(getattr(row, "timestamp"))
            w_start = t0 - self.touchdown_pre_sec
            w_end = t0 + self.touchdown_post_sec

            vz_vals: Dict[str, float | None] = {"IRS1": None, "IRS2": None, "IRS3": None}
            az_peak_vals: Dict[str, float | None] = {"IRS1": None, "IRS2": None, "IRS3": None}
            chart_series = []

            for name in ("IRS1", "IRS2", "IRS3"):
                df = irs_by_name.get(name)
                if df is None or df.empty or "timestamp" not in df.columns:
                    continue
                seg = df[(df["timestamp"] >= w_start) & (df["timestamp"] <= w_end)].copy()
                if seg.empty:
                    continue

                if "vertical_velocity" in seg.columns:
                    idx = (seg["timestamp"] - t0).abs().idxmin()
                    vz_vals[name] = _safe_float(seg.loc[idx, "vertical_velocity"])
                if "accel_z" in seg.columns:
                    az_peak_vals[name] = _safe_float(pd.to_numeric(seg["accel_z"], errors="coerce").abs().max())

                chart_series.append({
                    "irs": name,
                    "timestamps": [float(x) for x in seg["timestamp"].tolist()],
                    "t_rel": [float(x - t0) for x in seg["timestamp"].tolist()],
                    "vertical_velocity": [(_safe_float(x) if x is not None else None) for x in seg.get("vertical_velocity", pd.Series(dtype=float)).tolist()],
                    "accel_z": [(_safe_float(x) if x is not None else None) for x in seg.get("accel_z", pd.Series(dtype=float)).tolist()],
                })

            vz_non_null = [v for v in vz_vals.values() if v is not None]
            az_non_null = [v for v in az_peak_vals.values() if v is not None]
            vz_spread = (max(vz_non_null) - min(vz_non_null)) if len(vz_non_null) >= 2 else None
            az_spread = (max(az_non_null) - min(az_non_null)) if len(az_non_null) >= 2 else None

            # 粗略评级：使用三机绝对垂直速度最大值和过载峰值
            vz_abs_max = max((abs(v) for v in vz_non_null), default=0.0)
            az_abs_max = max((abs(v) for v in az_non_null), default=0.0)
            if vz_abs_max >= 3.0 or az_abs_max >= 2.0:
                rating = "heavy"
            elif vz_abs_max >= 1.8 or az_abs_max >= 1.5:
                rating = "attention"
            else:
                rating = "normal"

            summary = (
                f"触底时刻 {_fmt_ts(t0)}，|Vz|max={vz_abs_max:.3f} m/s，"
                f"|Az|max={az_abs_max:.3f} m/s²。"
            )

            results.append(
                TouchdownResult(
                    sequence=i,
                    touchdown_ts=t0,
                    touchdown_time=_fmt_ts(t0),
                    irs1_vz=vz_vals["IRS1"],
                    irs2_vz=vz_vals["IRS2"],
                    irs3_vz=vz_vals["IRS3"],
                    vz_spread=vz_spread,
                    irs1_az_peak=az_peak_vals["IRS1"],
                    irs2_az_peak=az_peak_vals["IRS2"],
                    irs3_az_peak=az_peak_vals["IRS3"],
                    az_peak_spread=az_spread,
                    rating=rating,
                    summary=summary,
                    chart_data={
                        "touchdown_ts": t0,
                        "window_start": w_start,
                        "window_end": w_end,
                        "series": chart_series,
                    },
                )
            )
        return results

    def _analyze_steady_states(self, auto_df: pd.DataFrame) -> List[SteadyStateResult]:
        needed = {"ap_engaged", "at_engaged", "lon_mode_active", "af_warning", "timestamp"}
        if not needed.issubset(set(auto_df.columns)):
            return []

        df = auto_df.copy()
        ap = pd.to_numeric(df["ap_engaged"], errors="coerce").fillna(0)
        at = pd.to_numeric(df["at_engaged"], errors="coerce").fillna(0)
        lon_mode = pd.to_numeric(df["lon_mode_active"], errors="coerce").fillna(-1)
        warning = pd.to_numeric(df["af_warning"], errors="coerce").fillna(255)
        steady_mask = (ap == 1) & (at == 1) & (lon_mode == 5) & (warning == 0)

        segments: List[tuple[int, int]] = []
        start = None
        for idx, flag in enumerate(steady_mask.tolist()):
            if flag and start is None:
                start = idx
            if (not flag) and start is not None:
                segments.append((start, idx - 1))
                start = None
        if start is not None:
            segments.append((start, len(df) - 1))

        results: List[SteadyStateResult] = []
        seq = 1
        for s, e in segments:
            seg = df.iloc[s:e + 1].copy()
            if seg.empty:
                continue
            duration = float(seg["timestamp"].iloc[-1] - seg["timestamp"].iloc[0])
            if duration < self.steady_min_sec:
                continue

            alt_series = seg.get("vert_track_error_m", pd.Series(dtype=float))
            lat_series = seg.get("lat_track_error_m", pd.Series(dtype=float))
            spd_series = pd.to_numeric(seg.get("current_airspeed_mps", pd.Series(dtype=float)), errors="coerce") - pd.to_numeric(
                seg.get("speed_cmd_mps", pd.Series(dtype=float)), errors="coerce"
            )

            alt_rms = _rms(alt_series)
            lat_rms = _rms(lat_series)
            spd_rms = _rms(spd_series)
            alt_max = _max_abs(alt_series)
            lat_max = _max_abs(lat_series)
            spd_max = _max_abs(spd_series)

            if (alt_max or 0.0) >= 30 or (lat_max or 0.0) >= 60 or (spd_max or 0.0) >= 5:
                rating = "attention"
            else:
                rating = "normal"

            st = float(seg["timestamp"].iloc[0])
            ed = float(seg["timestamp"].iloc[-1])
            summary = (
                f"稳态段 {_fmt_ts(st)} ~ {_fmt_ts(ed)}，"
                f"高度RMS={alt_rms if alt_rms is not None else float('nan'):.3f}m，"
                f"水平RMS={lat_rms if lat_rms is not None else float('nan'):.3f}m，"
                f"速度RMS={spd_rms if spd_rms is not None else float('nan'):.3f}m/s。"
            )

            results.append(
                SteadyStateResult(
                    sequence=seq,
                    start_ts=st,
                    end_ts=ed,
                    start_time=_fmt_ts(st),
                    end_time=_fmt_ts(ed),
                    duration_s=duration,
                    mode_label="AP+AT+ALT(纵向)+无告警",
                    alt_bias=_bias(alt_series),
                    alt_rms=alt_rms,
                    alt_max_abs=alt_max,
                    lat_bias=_bias(lat_series),
                    lat_rms=lat_rms,
                    lat_max_abs=lat_max,
                    spd_bias=_bias(spd_series),
                    spd_rms=spd_rms,
                    spd_max_abs=spd_max,
                    rating=rating,
                    summary=summary,
                    chart_data={
                        "timestamps": [float(x) for x in seg["timestamp"].tolist()],
                        "alt_error": [(_safe_float(x) if x is not None else None) for x in pd.to_numeric(alt_series, errors="coerce").tolist()],
                        "lat_error": [(_safe_float(x) if x is not None else None) for x in pd.to_numeric(lat_series, errors="coerce").tolist()],
                        "spd_error": [(_safe_float(x) if x is not None else None) for x in pd.to_numeric(spd_series, errors="coerce").tolist()],
                    },
                )
            )
            seq += 1
        return results
