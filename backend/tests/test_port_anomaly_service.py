# -*- coding: utf-8 -*-
"""端口异常分析：卡死 / 跳变 规则验证（不依赖数据库）。"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.parser_service import ParserService
from app.services.port_anomaly_service import PortAnomalyService, STUCK_CONSECUTIVE_FRAMES


@pytest.fixture
def parser_service():
    return ParserService(MagicMock())


def _write_parquet(path: Path, table: pa.Table) -> None:
    pq.write_table(table, path)


def test_stuck_five_identical_frames(parser_service, tmp_path):
    """连续 5 帧相同 → 产生一条卡死区间。"""
    ts = list(range(1, 12))
    # 前 5 帧为 1.0，第 6 帧起变化，卡死区间应在值变化时闭合
    vals = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 3.0]
    table = pa.table({"timestamp": ts, "heading": vals})
    p = tmp_path / "t.parquet"
    _write_parquet(p, table)

    pas = PortAnomalyService(parser_service)
    out = pas._analyze_scan(p, ["heading"], {})

    stuck = out["stuck_events"]
    assert len(stuck) >= 1
    first = stuck[0]
    assert first["field_name"] == "heading"
    assert first["frame_count"] == STUCK_CONSECUTIVE_FRAMES
    assert first["start_ts"] == 1.0
    assert first["end_ts"] == 5.0


def test_jump_kalman_spike_detected(parser_service, tmp_path):
    """平稳段后单帧突变 → 卡尔曼预测仍接近原水平，跳变告警（阈值足够小）。"""
    ts = list(range(1, 10))
    vals = [1.0, 1.0, 1.0, 1.0, 1.0, 50.0, 1.0, 1.0, 1.0]
    table = pa.table({"timestamp": ts, "signal": vals})
    p = tmp_path / "t.parquet"
    _write_parquet(p, table)

    pas = PortAnomalyService(parser_service)
    out = pas._analyze_scan(p, ["signal"], {"signal": 1.0})  # 1% 阈值

    jumps = out["jump_events"]
    assert len(jumps) >= 1
    j = jumps[0]
    assert j["field_name"] == "signal"
    assert j["timestamp"] == 6.0
    # 卡尔曼先验在突变前应贴近 1.0，允许数值漂移
    assert abs(j["predicted_value"] - 1.0) < 0.05
    assert j["current_value"] == 50.0
    assert j["deviation_pct"] > 1.0


def test_smooth_ramp_no_false_alarm(parser_service, tmp_path):
    """缓慢线性渐变不应产生跳变告警（相对阈值 2%）。"""
    n = 80
    ts = list(range(1, n + 1))
    base = 100.0
    step = 0.05
    vals = [base + i * step for i in range(n)]
    table = pa.table({"timestamp": ts, "slow": vals})
    p = tmp_path / "ramp.parquet"
    _write_parquet(p, table)

    pas = PortAnomalyService(parser_service)
    out = pas._analyze_scan(p, ["slow"], {"slow": 2.0})

    assert out["jump_events"] == []


def test_parser_id_isolation_defaults(tmp_path, monkeypatch):
    """不同 parser_id 对应不同 Parquet 文件时，defaults 只读目标文件。"""
    from app.services import port_anomaly_service as mod

    task_dir = tmp_path / "results" / "999"
    task_dir.mkdir(parents=True)
    p1 = task_dir / "port_1.parquet"
    p2 = task_dir / "port_1_parser_2.parquet"
    _write_parquet(p1, pa.table({"timestamp": [1.0], "a": [1]}))
    _write_parquet(p2, pa.table({"timestamp": [1.0], "b": [2]}))

    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)

    ps = ParserService(MagicMock())
    pas = PortAnomalyService(ps)

    fields1, _ = pas.get_numeric_fields_and_defaults(999, 1, None)
    fields2, _ = pas.get_numeric_fields_and_defaults(999, 1, 2)
    assert "a" in fields1 and "b" not in fields1
    assert "b" in fields2 and "a" not in fields2
