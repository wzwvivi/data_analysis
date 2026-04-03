# -*- coding: utf-8 -*-
"""端口解析结果异常分析：跳变（相对卡尔曼滤波预测）与卡死（连续相同值）。"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa

from ..config import DATA_DIR
from .parser_service import ParserService

# 连续多少帧相同视为可能卡死
STUCK_CONSECUTIVE_FRAMES = 5

# 跳变：相对偏差分母保护（避免除以 0）
JUMP_DENOM_EPS = 1e-9

# 标量卡尔曼（随机游走过程模型）：过程噪声方差 Q、观测噪声方差 R
DEFAULT_KALMAN_PROCESS_NOISE = 1e-6
DEFAULT_KALMAN_MEASUREMENT_NOISE = 0.25

# 字段名 -> 默认跳变告警阈值（相对卡尔曼预测值的百分比偏差）
FIELD_JUMP_THRESHOLD_PCT_DEFAULTS: Dict[str, float] = {
    # IRS 惯导常见字段
    "heading": 2.0,
    "pitch": 2.0,
    "roll": 2.0,
    "east_velocity": 5.0,
    "north_velocity": 5.0,
    "vertical_velocity": 5.0,
    "latitude": 0.5,
    "longitude": 0.5,
    "altitude": 2.0,
    "angular_rate_x": 5.0,
    "angular_rate_y": 5.0,
    "angular_rate_z": 5.0,
    "accel_x": 10.0,
    "accel_y": 10.0,
    "accel_z": 10.0,
    # RTK 等
    "latitude_deg": 0.5,
    "longitude_deg": 0.5,
    "altitude_ft": 2.0,
    "ground_speed_kn": 5.0,
    "track_angle_deg": 2.0,
    "hdop": 20.0,
    "vdop": 20.0,
}

# 未单独配置时的全局默认
DEFAULT_JUMP_THRESHOLD_PCT = 5.0


def resolve_jump_threshold_pct(field_name: str) -> float:
    if field_name in FIELD_JUMP_THRESHOLD_PCT_DEFAULTS:
        return FIELD_JUMP_THRESHOLD_PCT_DEFAULTS[field_name]
    # 后缀/包含匹配（小写）
    lower = field_name.lower()
    for key, val in FIELD_JUMP_THRESHOLD_PCT_DEFAULTS.items():
        if key in lower or lower.endswith("_" + key) or lower.startswith(key + "_"):
            return val
    return DEFAULT_JUMP_THRESHOLD_PCT


def _is_numeric_arrow_type(t: pa.DataType) -> bool:
    return (
        pa.types.is_integer(t)
        or pa.types.is_floating(t)
        or pa.types.is_decimal(t)
    )


def _values_close(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and (math.isnan(a) or math.isinf(a)):
            return False
        if isinstance(b, float) and (math.isnan(b) or math.isinf(b)):
            return False
        if isinstance(a, int) and isinstance(b, int):
            return a == b
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


class _ScalarKalman1D:
    """
    一维随机游走 + 高斯观测的标量卡尔曼滤波。
    每步：用上一时刻后验得到当前先验 x_prior，供跳变与观测比较；再用观测 z 更新后验。
    首帧仅初始化，返回 None（避免冷启动误报）。
    """

    __slots__ = ("_q", "_r", "_x", "_p", "_initialized")

    def __init__(self, process_variance: float, measurement_variance: float):
        self._q = max(float(process_variance), 1e-18)
        self._r = max(float(measurement_variance), 1e-18)
        self._x = 0.0
        self._p = self._r
        self._initialized = False

    def reset(self) -> None:
        self._x = 0.0
        self._p = self._r
        self._initialized = False

    def step(self, z: float) -> Optional[float]:
        """
        用观测 z 推进滤波器。
        返回：可与当前观测比较的先验预测 x_prior；首帧初始化时返回 None。
        """
        if not self._initialized:
            self._x = z
            self._p = self._r
            self._initialized = True
            return None

        x_prior = self._x
        p_prior = self._p + self._q
        denom = p_prior + self._r
        k = p_prior / denom if denom > 0 else 0.0
        self._x = x_prior + k * (z - x_prior)
        self._p = (1.0 - k) * p_prior
        return x_prior


class PortAnomalyService:
    """基于 Parquet 解析结果的端口级异常分析。"""

    def __init__(self, parser_service: ParserService):
        self._ps = parser_service

    def get_numeric_fields_and_defaults(
        self, task_id: int, port_number: int, parser_id: Optional[int] = None
    ) -> Tuple[List[str], Dict[str, float]]:
        """返回可分析的数值字段列表及每字段默认跳变阈值（%）。"""
        result_dir = DATA_DIR / "results" / str(task_id)
        path = self._ps._find_parquet_file(result_dir, port_number, parser_id)
        if not path or not path.exists():
            return [], {}
        dataset = pa.dataset.dataset(str(path), format="parquet")
        schema = dataset.schema
        names = schema.names
        numeric = []
        for name in names:
            if name == "timestamp":
                continue
            try:
                idx = schema.get_field_index(name)
                t = schema.field(idx).type
            except Exception:
                continue
            if _is_numeric_arrow_type(t):
                numeric.append(name)
        defaults = {n: resolve_jump_threshold_pct(n) for n in numeric}
        return numeric, defaults

    def analyze(
        self,
        task_id: int,
        port_number: int,
        fields: List[str],
        parser_id: Optional[int] = None,
        jump_threshold_pct_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        对指定字段做跳变与卡死分析。数据按 Parquet 行顺序读取（解析写入通常为时间序）。
        """
        overrides = jump_threshold_pct_overrides or {}
        result_dir = DATA_DIR / "results" / str(task_id)
        path = self._ps._find_parquet_file(result_dir, port_number, parser_id)
        if not path or not path.exists():
            raise FileNotFoundError("解析结果文件不存在")

        # 校验字段存在且为数值
        numeric_all, _ = self.get_numeric_fields_and_defaults(task_id, port_number, parser_id)
        numeric_set = set(numeric_all)
        use_fields = [f for f in fields if f in numeric_set]
        if not use_fields:
            return {
                "summary": {
                    "fields_analyzed": 0,
                    "jump_count": 0,
                    "stuck_count": 0,
                    "first_anomaly_ts": None,
                    "last_anomaly_ts": None,
                },
                "jump_events": [],
                "stuck_events": [],
                "stuck_consecutive_frames": STUCK_CONSECUTIVE_FRAMES,
                "message": "没有可分析的数值字段或所选字段无效",
            }

        return self._analyze_scan(path, use_fields, overrides)

    def _analyze_scan(
        self,
        path: Path,
        use_fields: List[str],
        overrides: Dict[str, float],
    ) -> Dict[str, Any]:
        cols = ["timestamp"] + use_fields
        batches, _ = self._ps._iter_filtered_batches(
            path, columns=cols, time_start=None, time_end=None
        )

        jump_events: List[Dict[str, Any]] = []
        stuck_events: List[Dict[str, Any]] = []

        # 每字段：独立卡尔曼滤波器（跳变预测）
        kalman_filters: Dict[str, _ScalarKalman1D] = {
            f: _ScalarKalman1D(
                DEFAULT_KALMAN_PROCESS_NOISE,
                DEFAULT_KALMAN_MEASUREMENT_NOISE,
            )
            for f in use_fields
        }
        # 卡死：连续相同值的 (first_ts, last_ts, value, count)
        stuck_state: Dict[str, Optional[Dict[str, Any]]] = {f: None for f in use_fields}

        first_anomaly: Optional[float] = None
        last_anomaly: Optional[float] = None

        def note_anomaly(t: float):
            nonlocal first_anomaly, last_anomaly
            if first_anomaly is None or t < first_anomaly:
                first_anomaly = t
            if last_anomaly is None or t > last_anomaly:
                last_anomaly = t

        def close_stuck(field: str):
            st = stuck_state[field]
            if st and st["count"] >= STUCK_CONSECUTIVE_FRAMES:
                stuck_events.append(
                    {
                        "field_name": field,
                        "start_ts": st["start_ts"],
                        "end_ts": st["end_ts"],
                        "frame_count": st["count"],
                        "stuck_value": st["value_raw"],
                    }
                )
                note_anomaly(st["start_ts"])
                note_anomaly(st["end_ts"])
            stuck_state[field] = None

        for batch in batches:
            n = batch.num_rows
            if n <= 0:
                continue
            ts_list = batch.column("timestamp").to_pylist()
            field_cols = {f: batch.column(f).to_pylist() for f in use_fields}

            for i in range(n):
                ts = ts_list[i]
                if ts is None:
                    continue
                try:
                    ts_f = float(ts)
                except (TypeError, ValueError):
                    continue

                for field in use_fields:
                    raw = field_cols[field][i]
                    cur_f = _to_float(raw)
                    thresh = overrides.get(field, resolve_jump_threshold_pct(field))

                    # --- 卡死 ---
                    st = stuck_state[field]
                    if cur_f is None:
                        close_stuck(field)
                        kalman_filters[field].reset()
                        continue

                    if st is None:
                        stuck_state[field] = {
                            "start_ts": ts_f,
                            "end_ts": ts_f,
                            "value_raw": raw,
                            "count": 1,
                        }
                    elif _values_close(raw, st["value_raw"]):
                        st["end_ts"] = ts_f
                        st["count"] += 1
                    else:
                        close_stuck(field)
                        stuck_state[field] = {
                            "start_ts": ts_f,
                            "end_ts": ts_f,
                            "value_raw": raw,
                            "count": 1,
                        }

                    # --- 跳变：卡尔曼先验预测 vs 当前观测 ---
                    pred = kalman_filters[field].step(cur_f)
                    if pred is not None:
                        denom = max(abs(pred), JUMP_DENOM_EPS)
                        dev_pct = abs(cur_f - pred) / denom * 100.0
                        if dev_pct > thresh:
                            jump_events.append(
                                {
                                    "field_name": field,
                                    "timestamp": ts_f,
                                    "current_value": cur_f,
                                    "predicted_value": pred,
                                    "deviation_pct": round(dev_pct, 6),
                                    "threshold_pct": thresh,
                                }
                            )
                            note_anomaly(ts_f)

        for field in use_fields:
            close_stuck(field)

        summary = {
            "fields_analyzed": len(use_fields),
            "jump_count": len(jump_events),
            "stuck_count": len(stuck_events),
            "first_anomaly_ts": first_anomaly,
            "last_anomaly_ts": last_anomaly,
        }
        return {
            "summary": summary,
            "jump_events": jump_events,
            "stuck_events": stuck_events,
            "stuck_consecutive_frames": STUCK_CONSECUTIVE_FRAMES,
        }
