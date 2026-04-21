import os
import re
import sqlite3
import json
import io
import csv
import shutil
import tempfile
import threading
import uuid
import traceback
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file, Response
import pandas as pd
import numpy as np

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    'FLIGHT_DATA_DB_PATH',
    os.path.join(BASE_DIR, 'data', 'flight_data.db'),
)
UPLOAD_FOLDER = os.environ.get(
    'FLIGHT_DATA_UPLOAD_DIR',
    os.path.join(BASE_DIR, 'uploads'),
)

os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------- Database ---------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            batch_name TEXT,
            row_count INTEGER DEFAULT 0,
            col_count INTEGER DEFAULT 0,
            time_min_str TEXT,
            time_max_str TEXT,
            time_min_seconds REAL,
            time_max_seconds REAL,
            source_files TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS dataset_columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            col_index INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            col_type TEXT NOT NULL DEFAULT 'text',
            FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE,
            UNIQUE(dataset_id, col_index)
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name TEXT NOT NULL UNIQUE,
            result TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    # Migrate existing DB if needed
    try:
        conn.execute("ALTER TABLE datasets ADD COLUMN source_files TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


init_db()


# --------------- Task Progress Tracking ---------------

_tasks = {}
_tasks_lock = threading.Lock()


def create_task():
    task_id = uuid.uuid4().hex[:12]
    with _tasks_lock:
        _tasks[task_id] = {
            'status': 'uploading',
            'phase': 'Saving uploaded files...',
            'total': 0,
            'last_heartbeat': time.time(),
            'processed': 0,
            'current_name': '',
            'results': [],
            'error': None,
            'batch_name': '',
        }
    return task_id


def update_task(task_id, **kwargs):
    with _tasks_lock:
        if task_id in _tasks:
            kwargs['last_heartbeat'] = time.time()
            _tasks[task_id].update(kwargs)


def get_task(task_id):
    with _tasks_lock:
        t = _tasks.get(task_id)
        if not t:
            return {}
        result = dict(t)
        result['seconds_since_update'] = round(time.time() - t.get('last_heartbeat', time.time()), 1)
        return result


def cleanup_task(task_id, delay=300):
    def _remove():
        with _tasks_lock:
            _tasks.pop(task_id, None)
    timer = threading.Timer(delay, _remove)
    timer.daemon = True
    timer.start()


# --------------- File Processing ---------------

def get_group_key(filename):
    name = filename
    if name.lower().endswith('.csv'):
        name = name[:-4]
    match = re.match(r'^(.+)_(\d+)$', name)
    if match:
        return match.group(1), int(match.group(2))
    return name, 0


def detect_col_type(series):
    non_null = series.dropna()
    if len(non_null) == 0:
        return 'text'
    sample = non_null.head(100)
    if sample.astype(str).str.contains(r'[\[\]]', regex=True).any():
        return 'text'
    try:
        pd.to_numeric(sample, errors='raise')
        return 'numeric'
    except (ValueError, TypeError):
        return 'text'


def make_display_name(original_name):
    parts = original_name.split('.')
    if len(parts) >= 4 and parts[0] == 'root':
        return '.'.join(parts[3:])
    return original_name


def process_and_store(file_group, group_name, batch_name, conn, source_files=None):
    """Process a group of CSV files: merge, sort, transform time, store in DB."""
    file_group.sort(key=lambda x: x[1])

    dfs = []
    for filepath, chunk_num in file_group:
        try:
            df = pd.read_csv(filepath, float_precision='round_trip')
            if len(df) > 0:
                dfs.append(df)
        except Exception as e:
            print(f"Warning: Failed to read {filepath}: {e}")
            continue

    if not dfs:
        return None

    merged = pd.concat(dfs, ignore_index=True)

    if 'Time' not in merged.columns:
        print(f"Warning: No 'Time' column in {group_name}")
        return None

    merged['_parsed_time'] = pd.to_datetime(merged['Time'], errors='coerce')
    merged = merged.dropna(subset=['_parsed_time'])
    merged = merged.sort_values('_parsed_time', ascending=True).reset_index(drop=True)

    t = merged['_parsed_time']
    milliseconds = (t.dt.microsecond // 1000).astype(str).str.zfill(3)
    merged['time_str'] = t.dt.strftime('%H:%M:%S.') + milliseconds
    merged['time_seconds'] = (
        t.dt.hour * 3600 + t.dt.minute * 60 + t.dt.second + t.dt.microsecond / 1e6
    ).round(2)

    merged = merged.drop(columns=['_parsed_time', 'Time'])

    data_cols = [c for c in merged.columns if c not in ('time_str', 'time_seconds')]
    mavtype_cols = [c for c in data_cols if c.endswith('.mavpackettype')]
    data_cols = [c for c in data_cols if c not in mavtype_cols]
    merged = merged.drop(columns=mavtype_cols, errors='ignore')

    col_types = {}
    for col in data_cols:
        col_types[col] = detect_col_type(merged[col])

    for col in data_cols:
        if col_types[col] == 'numeric':
            merged[col] = pd.to_numeric(merged[col], errors='coerce')

    final_cols = ['time_str', 'time_seconds'] + data_cols
    merged = merged[final_cols]

    row_count = len(merged)
    if row_count == 0:
        return None

    cursor = conn.execute(
        """INSERT INTO datasets (name, batch_name, row_count, col_count,
           time_min_str, time_max_str, time_min_seconds, time_max_seconds, source_files)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            group_name, batch_name, row_count, len(data_cols),
            merged['time_str'].iloc[0], merged['time_str'].iloc[-1],
            float(merged['time_seconds'].iloc[0]), float(merged['time_seconds'].iloc[-1]),
            json.dumps(source_files) if source_files else None
        )
    )
    dataset_id = cursor.lastrowid

    for i, col in enumerate(data_cols):
        display = make_display_name(col)
        conn.execute(
            "INSERT INTO dataset_columns (dataset_id, col_index, original_name, display_name, col_type) VALUES (?, ?, ?, ?, ?)",
            (dataset_id, i, col, display, col_types[col])
        )

    col_defs = ["row_id INTEGER PRIMARY KEY AUTOINCREMENT",
                "time_str TEXT", "time_seconds REAL"]
    for i, col in enumerate(data_cols):
        sql_type = "REAL" if col_types[col] == 'numeric' else "TEXT"
        col_defs.append(f"c{i} {sql_type}")

    table_name = f"data_{dataset_id}"
    conn.execute(f"CREATE TABLE [{table_name}] ({', '.join(col_defs)})")
    conn.execute(f"CREATE INDEX idx_{dataset_id}_time ON [{table_name}] (time_seconds)")

    insert_cols = ["time_str", "time_seconds"] + [f"c{i}" for i in range(len(data_cols))]
    placeholders = ", ".join(["?"] * len(insert_cols))
    insert_sql = f"INSERT INTO [{table_name}] ({', '.join(insert_cols)}) VALUES ({placeholders})"

    insert_data = merged[final_cols].values.tolist()
    clean_data = []
    for row in insert_data:
        clean_row = []
        for val in row:
            if isinstance(val, (np.integer,)):
                clean_row.append(int(val))
            elif isinstance(val, (np.floating,)):
                clean_row.append(None if np.isnan(val) else float(val))
            elif isinstance(val, np.bool_):
                clean_row.append(int(val))
            elif pd.isna(val):
                clean_row.append(None)
            else:
                clean_row.append(val)
        clean_data.append(clean_row)

    BATCH_SIZE = 5000
    for i in range(0, len(clean_data), BATCH_SIZE):
        conn.executemany(insert_sql, clean_data[i:i + BATCH_SIZE])

    conn.commit()
    return dataset_id


# --------------- Flight Analysis ---------------

def fmt_time(seconds):
    """Convert seconds to HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def fmt_duration(seconds):
    """Human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}min"


def find_dataset(conn, batch_name, pattern):
    """Find a dataset in a batch by name pattern."""
    row = conn.execute(
        "SELECT id, name FROM datasets WHERE batch_name = ? AND name LIKE ?",
        (batch_name, f'%{pattern}%')
    ).fetchone()
    return row


def load_column(conn, dataset_id, display_pattern, max_points=3000):
    """Load a downsampled column from a dataset."""
    col = conn.execute(
        "SELECT col_index FROM dataset_columns WHERE dataset_id = ? AND display_name LIKE ?",
        (dataset_id, f'%{display_pattern}%')
    ).fetchone()
    if not col:
        return None, None
    ci = col['col_index']
    table_name = f"data_{dataset_id}"
    total = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
    step = max(1, total // max_points)
    rows = conn.execute(
        f"SELECT time_seconds, c{ci} FROM [{table_name}] WHERE row_id % ? = 0 ORDER BY time_seconds",
        (step,)
    ).fetchall()
    times = [r[0] for r in rows if r[1] is not None]
    values = [r[1] for r in rows if r[1] is not None]
    return times, values


def load_columns_aligned(conn, dataset_id, patterns, max_points=3000, zero_filter_col=None):
    """Load multiple columns aligned by time, with optional zero-value filtering.

    Args:
        patterns: list of display_name LIKE patterns
        zero_filter_col: index into patterns; rows where this column == 0 are dropped
                         (used to filter uninitialized default values)
    Returns:
        dict of {pattern: (times, values)}
    """
    col_infos = []
    for pat in patterns:
        col = conn.execute(
            "SELECT col_index FROM dataset_columns WHERE dataset_id = ? AND display_name LIKE ?",
            (dataset_id, f'%{pat}%')
        ).fetchone()
        col_infos.append(col['col_index'] if col else None)

    # Need at least one valid column
    valid_cis = [ci for ci in col_infos if ci is not None]
    if not valid_cis:
        return {pat: (None, None) for pat in patterns}

    table_name = f"data_{dataset_id}"
    total = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]").fetchone()[0]
    step = max(1, total // max_points)

    select_cols = ", ".join(f"c{ci}" if ci is not None else "NULL" for ci in col_infos)
    rows = conn.execute(
        f"SELECT time_seconds, {select_cols} FROM [{table_name}] WHERE row_id % ? = 0 ORDER BY time_seconds",
        (step,)
    ).fetchall()

    # Filter out rows where zero_filter_col is 0 or None (uninitialized data)
    filter_idx = zero_filter_col
    filtered = []
    for r in rows:
        if filter_idx is not None:
            val = r[1 + filter_idx]
            if val is None or val == 0:
                continue
        filtered.append(r)

    result = {}
    for i, pat in enumerate(patterns):
        if col_infos[i] is None:
            result[pat] = (None, None)
        else:
            times = [r[0] for r in filtered if r[1 + i] is not None]
            values = [r[1 + i] for r in filtered if r[1 + i] is not None]
            result[pat] = (times, values)
    return result


def detect_flight_phases(times, altitudes, speeds):
    """Detect flight phases from altitude and speed data."""
    if not times or len(times) < 10:
        return []

    alt = pd.Series(altitudes, dtype=float)
    spd = pd.Series(speeds, dtype=float) if speeds else pd.Series(np.zeros(len(times)))
    alt_smooth = alt.rolling(window=min(30, len(alt)//5 + 1), min_periods=1, center=True).mean()

    # Vertical rate (m/s)
    dt = np.diff(times)
    da = np.diff(alt_smooth.values)
    vrate = np.zeros(len(times))
    valid = dt > 0.01
    vrate[1:][valid] = da[valid] / dt[valid]
    vrate_smooth = pd.Series(vrate).rolling(window=min(50, len(vrate)//5 + 1), min_periods=1, center=True).mean()

    ground_alt = float(np.percentile(alt.iloc[:min(50, len(alt))], 50))

    phases = []
    state = 'Ground'
    start_idx = 0

    for i in range(len(times)):
        h = alt_smooth.iloc[i] - ground_alt
        v = spd.iloc[i]
        vr = vrate_smooth.iloc[i]
        new_state = state

        if state == 'Ground':
            if h > 5 and v > 3:
                new_state = 'Takeoff'
        elif state == 'Takeoff':
            if vr > 0.3 and h > 20:
                new_state = 'Climb'
            elif h < 2:
                new_state = 'Ground'
        elif state == 'Climb':
            if abs(vr) < 0.2 and h > 30:
                new_state = 'Cruise'
            elif vr < -0.3:
                new_state = 'Descent'
        elif state == 'Cruise':
            if vr > 0.5:
                new_state = 'Climb'
            elif vr < -0.5:
                new_state = 'Descent'
        elif state == 'Descent':
            if vr > 0.5:
                new_state = 'Climb'
            elif h < 10 and v < 10:
                new_state = 'Landing'
        elif state == 'Landing':
            if v < 1:
                new_state = 'Ground'

        if new_state != state:
            duration = times[i] - times[start_idx]
            if duration > 2:  # ignore very short phases
                phases.append({
                    'phase': state,
                    'start': fmt_time(times[start_idx]),
                    'end': fmt_time(times[i]),
                    'duration': fmt_duration(duration),
                })
            state = new_state
            start_idx = i

    # Final phase
    duration = times[-1] - times[start_idx]
    if duration > 2:
        phases.append({
            'phase': state,
            'start': fmt_time(times[start_idx]),
            'end': fmt_time(times[-1]),
            'duration': fmt_duration(duration),
        })

    return phases


def detect_anomalies(conn, batch_name):
    """Detect anomalies across datasets."""
    anomalies = []

    # Check altitude jumps (filter lat=0 rows = uninitialized INS)
    ds = find_dataset(conn, batch_name, 'INS_POSITION')
    if ds:
        ins_anom = load_columns_aligned(
            conn, ds['id'], ['%lat%', '%alt%'], max_points=5000, zero_filter_col=0
        )
        times, alts = ins_anom['%alt%']
        if times and len(times) > 10:
            alt_arr = np.array(alts, dtype=float)
            dt_arr = np.diff(times)
            da_arr = np.abs(np.diff(alt_arr))
            for i in range(len(da_arr)):
                if dt_arr[i] > 0 and da_arr[i] / max(dt_arr[i], 0.01) > 50:
                    anomalies.append({
                        'time': fmt_time(times[i+1]),
                        'type': 'Altitude Jump',
                        'detail': f'Altitude changed {da_arr[i]:.1f}m in {dt_arr[i]:.1f}s',
                        'severity': 'warning',
                        'source': 'INS_POSITION'
                    })
                    if len(anomalies) > 20:
                        break

    # Check battery SOC drops (filter SOC=0 = uninitialized BMS)
    ds = find_dataset(conn, batch_name, 'BMS_MAIN_DATA_1')
    if ds:
        bms_anom = load_columns_aligned(
            conn, ds['id'], ['%pack_soc%'], max_points=2000, zero_filter_col=0
        )
        times, socs = bms_anom['%pack_soc%']
        if times and len(times) > 10:
            soc_arr = np.array(socs, dtype=float)
            dt_arr = np.diff(times)
            dsoc = np.diff(soc_arr)
            for i in range(len(dsoc)):
                if dt_arr[i] > 0 and dsoc[i] < -2:
                    anomalies.append({
                        'time': fmt_time(times[i+1]),
                        'type': 'Battery SOC Drop',
                        'detail': f'SOC dropped {abs(dsoc[i]):.1f}% in {dt_arr[i]:.1f}s',
                        'severity': 'warning',
                        'source': 'BMS_MAIN_DATA'
                    })
                    if len(anomalies) > 30:
                        break

    # Check for FCC errors
    ds = find_dataset(conn, batch_name, 'FCC_DATA_1')
    if ds:
        cols = conn.execute(
            "SELECT col_index, display_name FROM dataset_columns WHERE dataset_id = ? AND display_name LIKE '%control_law_err%'",
            (ds['id'],)
        ).fetchall()
        for col_info in cols:
            ci = col_info['col_index']
            table_name = f"data_{ds['id']}"
            err_rows = conn.execute(
                f"SELECT time_str, c{ci} FROM [{table_name}] WHERE c{ci} IS NOT NULL AND c{ci} != '' AND c{ci} NOT LIKE '%0%0%0%0%' LIMIT 5"
            ).fetchall()
            for r in err_rows:
                val = r[1]
                if val and '1' in str(val):
                    anomalies.append({
                        'time': r[0],
                        'type': 'FCC Control Law Error',
                        'detail': f'{col_info["display_name"]}: {val}',
                        'severity': 'critical',
                        'source': 'FCC_DATA'
                    })

    return anomalies


# --------------- State-Change Event Detection ---------------

# Map column name patterns to human-readable event descriptions
EVENT_RULES = [
    # (dataset_pattern, col_pattern, label_prefix, value_interpreter)
    ('FCC_DATA_1', 'fcc_status_data', 'FCC Status', None),
    ('FCC_DATA_1', 'link_select', 'FCC Link Select', None),
    ('FCC_DATA_1', 'control_law_err1', 'Control Law Err1', None),
    ('FCC_DATA_1', 'control_law_err2', 'Control Law Err2', None),
    ('AUTO_GUIDE', 'lateral_mode', 'Lateral Mode', None),
    ('AUTO_GUIDE', 'long_mode', 'Longitudinal Mode', None),
    ('AUTO_GUIDE', 'throttle_mode', 'Throttle Mode', None),
    ('AUTO_GUIDE', 'active_state', 'AFCS Active State', None),
    ('AUTO_GUIDE', 'afcs_status_data', 'AFCS Status', None),
    ('LANDING_GEAR_WOW_DATA_1', 'lg_position_status', 'Landing Gear Position', None),
    ('LANDING_GEAR_WOW_DATA_1', 'lg_work_status', 'Landing Gear Work Status', None),
    ('LANDING_GEAR_WOW_DATA_1', 'data_valid', 'LG Data Valid', None),
    ('BRAKE_DATA_1', 'break_mode_data', 'Brake Mode', None),
    ('BRAKE_DATA_1', 'fcc_break_mode_cmd', 'FCC Brake Cmd', None),
    ('BRAKE_DATA_1', 'bcmu_cas1', 'BCMU CAS1', None),
    ('MANUAL_CONTROL', 'throttle_toga', 'TOGA Switch', None),
]


def detect_state_change_events(conn, batch_name, max_events=200):
    """Scan key text columns for state changes and return timed events."""
    events = []

    for ds_pattern, col_pattern, label, _ in EVENT_RULES:
        ds = find_dataset(conn, batch_name, ds_pattern)
        if not ds:
            continue

        col = conn.execute(
            "SELECT col_index, display_name FROM dataset_columns "
            "WHERE dataset_id = ? AND display_name LIKE ? AND col_type = 'text'",
            (ds['id'], f'%{col_pattern}%')
        ).fetchone()
        if not col:
            continue

        ci = col['col_index']
        table_name = f"data_{ds['id']}"
        # Read time + value, ordered by time
        rows = conn.execute(
            f"SELECT time_seconds, time_str, c{ci} FROM [{table_name}] ORDER BY time_seconds"
        ).fetchall()

        if not rows:
            continue

        prev_val = None
        for r in rows:
            val = r[2]
            if val != prev_val and prev_val is not None:
                events.append({
                    'time_seconds': r[0],
                    'time_str': r[1],
                    'label': label,
                    'from': str(prev_val),
                    'to': str(val),
                    'source': col['display_name'],
                    'dataset': re.sub(r'_\d{9,}$', '', ds['name']),
                })
            prev_val = val

        if len(events) > max_events * 3:
            break  # safety limit

    # Sort by time and deduplicate close events
    events.sort(key=lambda e: e['time_seconds'])

    # Merge events that happen within 0.5s of each other into groups
    merged = []
    for ev in events:
        if merged and abs(ev['time_seconds'] - merged[-1]['time_seconds']) < 0.5:
            # Append to previous event group
            if 'group' not in merged[-1]:
                merged[-1]['group'] = [{'label': merged[-1]['label'], 'from': merged[-1]['from'], 'to': merged[-1]['to'], 'dataset': merged[-1].get('dataset',''), 'source': merged[-1].get('source','')}]
                merged[-1]['label'] = 'Multiple changes'
            merged[-1]['group'].append({'label': ev['label'], 'from': ev['from'], 'to': ev['to'], 'dataset': ev.get('dataset',''), 'source': ev.get('source','')})
        else:
            merged.append(ev)

    return merged[:max_events]


# --------------- Flight Narrative Generator ---------------

def generate_narrative(result):
    """Generate a natural language description of the flight."""
    info = result.get('flight_info', {})
    profile = result.get('flight_profile', {})
    phases = result.get('phases', [])
    batt = result.get('battery', {})
    anomalies = result.get('anomalies', [])
    events = result.get('events', [])

    lines = []

    # Basic info
    lines.append(f"本架次数据记录时间为 {info.get('start_time','?')} 至 {info.get('end_time','?')}，"
                 f"总时长 {info.get('duration','?')}，共包含 {info.get('dataset_count',0)} 个数据集。")

    # Position
    if profile.get('start_position'):
        lines.append(f"起始位置 {profile['start_position']}，终止位置 {profile.get('end_position','?')}。")

    # Flight or ground
    has_flight = info.get('has_flight', False)
    alt_range = profile.get('altitude_range_m', 0)

    if not has_flight:
        lines.append(f"本架次高度变化仅 {alt_range:.1f}m（{profile.get('min_altitude_m','?')}m ~ {profile.get('max_altitude_m','?')}m），"
                     "未检测到明显的起飞/着陆过程，判断为地面运行/滑行数据。")
    else:
        lines.append(f"最大高度 {profile.get('max_altitude_m','?')}m，高度变化范围 {alt_range:.1f}m。")
        if profile.get('max_ground_speed'):
            lines.append(f"最大地速 {profile['max_ground_speed']} m/s。")
        if profile.get('max_airspeed'):
            lines.append(f"最大空速 {profile['max_airspeed']} m/s"
                         + (f"，最大马赫数 {profile['max_mach']}" if profile.get('max_mach') else "") + "。")

    # Phases
    if phases:
        phase_desc = []
        for p in phases:
            phase_desc.append(f"{p['phase']}({p['start']}~{p['end']}, {p['duration']})")
        lines.append("飞行阶段：" + " → ".join(phase_desc) + "。")

    # Battery
    if batt.get('initial_soc') is not None:
        consumed = batt.get('soc_consumed', 0)
        lines.append(f"电池 SOC 从 {batt['initial_soc']}% 变化至 {batt['final_soc']}%，消耗 {consumed}%。"
                     + (f"电压范围 {batt.get('voltage_min','?')}V ~ {batt.get('voltage_max','?')}V，" if batt.get('voltage_min') else "")
                     + (f"最高温度 {batt['temp_max']}°C。" if batt.get('temp_max') else ""))

    # Key events summary
    if events:
        # Count by label
        from collections import Counter
        label_counts = Counter(e['label'] for e in events)
        top_events = label_counts.most_common(8)
        ev_desc = "、".join(f"{name}({cnt}次)" for name, cnt in top_events)
        lines.append(f"共检测到 {len(events)} 个状态变化事件，主要包括：{ev_desc}。")

        # Describe first few interesting events chronologically
        interesting = [e for e in events if e['label'] not in ('Multiple changes',)][:5]
        if interesting:
            first_ev = interesting[0]
            ds_name = first_ev.get('dataset', '')
            lines.append(f"首个状态变化发生在 {first_ev['time_str']}（{ds_name}）：{first_ev['label']} 变为 {first_ev['to']}。")

    # Anomalies
    critical = [a for a in anomalies if a['severity'] == 'critical']
    warnings = [a for a in anomalies if a['severity'] == 'warning']
    if critical:
        lines.append(f"发现 {len(critical)} 个严重异常（Critical），涉及 "
                     + "、".join(set(a['type'] for a in critical)) + "，需重点关注。")
    if warnings:
        lines.append(f"发现 {len(warnings)} 个告警（Warning），涉及 "
                     + "、".join(set(a['type'] for a in warnings)) + "。")
    if not critical and not warnings:
        lines.append("未发现明显异常，本架次数据质量良好。")

    return "\n".join(lines)


def analyze_batch(batch_name):
    """Run comprehensive flight analysis on a batch."""
    conn = get_db()
    result = {
        'flight_info': {},
        'flight_profile': {},
        'battery': {},
        'phases': [],
        'anomalies': [],
        'quality': 'Good',
    }

    try:
        # 1. Overall time range
        row = conn.execute(
            "SELECT MIN(time_min_seconds) as t_min, MAX(time_max_seconds) as t_max, "
            "MIN(time_min_str) as t_min_str, MAX(time_max_str) as t_max_str, "
            "COUNT(*) as ds_count "
            "FROM datasets WHERE batch_name = ?",
            (batch_name,)
        ).fetchone()

        if not row or row['ds_count'] == 0:
            return result

        t_min = row['t_min']
        t_max = row['t_max']
        duration = t_max - t_min if t_min and t_max else 0

        result['flight_info'] = {
            'batch_name': batch_name,
            'dataset_count': row['ds_count'],
            'start_time': fmt_time(t_min) if t_min else 'N/A',
            'end_time': fmt_time(t_max) if t_max else 'N/A',
            'duration': fmt_duration(duration),
            'duration_seconds': round(duration, 2),
        }

        # 2. Flight profile from INS_POSITION
        #    Use lat as zero-filter column: lat=0 means INS not initialized
        ds_pos = find_dataset(conn, batch_name, 'INS_POSITION')
        if ds_pos:
            ins_data = load_columns_aligned(
                conn, ds_pos['id'],
                ['%lat%', '%lon%', '%alt%', '%ground_speed%'],
                max_points=3000,
                zero_filter_col=0  # filter rows where lat=0
            )
            times_lat, lats = ins_data['%lat%']
            times_lon, lons = ins_data['%lon%']
            times_alt, alts = ins_data['%alt%']
            times_spd, spds = ins_data['%ground_speed%']

            profile = {}
            if alts:
                profile['max_altitude_m'] = round(max(alts), 1)
                profile['min_altitude_m'] = round(min(alts), 1)
                profile['altitude_range_m'] = round(max(alts) - min(alts), 1)
            if spds:
                profile['max_ground_speed'] = round(max(spds), 1)
            if lats and lons:
                profile['start_position'] = f"{lats[0]:.6f}N, {lons[0]:.6f}E"
                profile['end_position'] = f"{lats[-1]:.6f}N, {lons[-1]:.6f}E"

            result['flight_profile'] = profile

            # Detect phases (using filtered data)
            if times_alt and alts:
                spd_aligned = spds if (spds and len(spds) == len(alts)) else None
                result['phases'] = detect_flight_phases(times_alt, alts, spd_aligned)

            # Trajectory data for ND/VD charts (already filtered by lat>0)
            traj_len = min(
                len(times_alt) if times_alt else 0,
                len(lats) if lats else 0,
                len(lons) if lons else 0,
            )
            has_spd = spds and len(spds) >= traj_len
            if traj_len > 0:
                traj = {
                    'time': [round(times_alt[i], 2) for i in range(traj_len)],
                    'lat':  [round(lats[i], 6) for i in range(traj_len)],
                    'lon':  [round(lons[i], 6) for i in range(traj_len)],
                    'alt':  [round(alts[i], 2) for i in range(traj_len)],
                }
                if has_spd:
                    traj['speed'] = [round(spds[i], 2) for i in range(traj_len)]
                traj['source_dataset'] = re.sub(r'_\d{9,}$', '', ds_pos['name'])
                result['trajectory'] = traj

        # 3. ADC data
        ds_adc = find_dataset(conn, batch_name, 'STANDARD_ADC_DATA')
        if ds_adc:
            _, airspeeds = load_column(conn, ds_adc['id'], '%air_speed%')
            _, machs = load_column(conn, ds_adc['id'], '%march%')
            if airspeeds:
                # Filter out zero airspeeds (uninitialized)
                valid_as = [v for v in airspeeds if v > 0]
                if valid_as:
                    result['flight_profile']['max_airspeed'] = round(max(valid_as), 1)
            if machs:
                valid_m = [v for v in machs if v > 0]
                if valid_m:
                    result['flight_profile']['max_mach'] = round(max(valid_m), 4)

        # 4. Battery — filter SOC=0 (uninitialized BMS default)
        ds_bms = find_dataset(conn, batch_name, 'BMS_MAIN_DATA_1')
        if not ds_bms:
            ds_bms = find_dataset(conn, batch_name, '800_BMS_MAIN_DATA_1')
        if ds_bms:
            bms_data = load_columns_aligned(
                conn, ds_bms['id'],
                ['%pack_soc%', '%pack_voltage%', '%pack_total_current%', '%max_cell_temp%'],
                max_points=2000,
                zero_filter_col=0  # filter rows where SOC=0
            )
            _, socs = bms_data['%pack_soc%']
            _, volts = bms_data['%pack_voltage%']
            _, currents = bms_data['%pack_total_current%']
            _, temps = bms_data['%max_cell_temp%']
            batt = {}
            if socs:
                batt['initial_soc'] = round(socs[0], 1)
                batt['final_soc'] = round(socs[-1], 1)
                batt['soc_consumed'] = round(socs[0] - socs[-1], 1)
            if volts:
                batt['voltage_min'] = round(min(volts), 2)
                batt['voltage_max'] = round(max(volts), 2)
            if currents:
                batt['current_max'] = round(max(currents), 1)
            if temps:
                batt['temp_max'] = round(max(temps), 1)
            result['battery'] = batt

        # 5. Anomalies
        result['anomalies'] = detect_anomalies(conn, batch_name)

        # 6. Quality assessment
        critical_count = sum(1 for a in result['anomalies'] if a['severity'] == 'critical')
        warning_count = sum(1 for a in result['anomalies'] if a['severity'] == 'warning')

        if critical_count > 0:
            result['quality'] = 'Critical'
        elif warning_count > 5:
            result['quality'] = 'Warning'
        elif warning_count > 0:
            result['quality'] = 'Minor Issues'
        else:
            result['quality'] = 'Good'

        has_flight = result['flight_profile'].get('altitude_range_m', 0) > 20
        result['flight_info']['has_flight'] = has_flight
        if not has_flight:
            result['flight_info']['note'] = 'Data appears to be ground-only (no significant altitude change detected)'

        # 6. State-change events
        result['events'] = detect_state_change_events(conn, batch_name)

        # 7. Natural language narrative
        result['narrative'] = generate_narrative(result)

    except Exception as e:
        result['error'] = str(e)
        traceback.print_exc()
    finally:
        conn.close()

    return result


# --------------- Routes ---------------

@app.route('/')
def index():
    return render_template('index.html')


def _background_process(task_id, tmp_dir, groups, batch_name, file_stats=None):
    """Background thread: merge and store each file group, updating progress."""
    file_stats = file_stats or {}
    try:
        total = len(groups)
        update_task(task_id, status='processing', total=total, processed=0,
                    phase='Merging and storing data...')

        conn = get_db()
        results = []        # successfully created datasets
        failed_groups = []   # groups that failed to process
        skipped_groups = []  # groups skipped (e.g. no Time column, empty)

        for idx, (group_name, file_group) in enumerate(sorted(groups.items())):
            short_name = re.sub(r'_\d{9,}$', '', group_name)
            update_task(task_id, processed=idx, current_name=short_name,
                        phase=f'Processing ({idx+1}/{total}): {short_name}')
            try:
                source_files = sorted([os.path.basename(fp) for fp, _ in file_group])
                dataset_id = process_and_store(file_group, group_name, batch_name, conn, source_files)
                if dataset_id:
                    results.append({
                        'id': dataset_id,
                        'name': group_name,
                        'short_name': short_name,
                        'files_merged': len(file_group),
                        'source_files': source_files,
                    })
                else:
                    skipped_groups.append({
                        'name': group_name,
                        'short_name': short_name,
                        'files': len(file_group),
                        'reason': 'No valid data (missing Time column or empty)',
                    })
            except Exception as e:
                print(f"Error processing {group_name}: {e}")
                traceback.print_exc()
                failed_groups.append({
                    'name': group_name,
                    'short_name': short_name,
                    'files': len(file_group),
                    'reason': str(e),
                })

        conn.close()

        # Run flight analysis
        update_task(task_id, processed=total, current_name='',
                    phase='Analyzing flight data...')
        analysis = analyze_batch(batch_name)
        conn2 = get_db()
        conn2.execute(
            "INSERT OR REPLACE INTO analyses (batch_name, result) VALUES (?, ?)",
            (batch_name, json.dumps(analysis, ensure_ascii=False))
        )
        conn2.commit()
        conn2.close()

        # Build upload summary
        total_source_files = sum(r['files_merged'] for r in results)
        upload_summary = {
            'total_files_received': file_stats.get('total_files_received', 0),
            'csv_files_count': file_stats.get('csv_files', 0),
            'non_csv_skipped': file_stats.get('non_csv_skipped', []),
            'total_groups': total,
            'datasets_created': len(results),
            'groups_skipped': len(skipped_groups),
            'groups_failed': len(failed_groups),
            'total_source_files_merged': total_source_files,
            'merge_details': results,
            'skipped_details': skipped_groups,
            'failed_details': failed_groups,
        }

        update_task(task_id, status='done', processed=total, current_name='',
                    phase='All done!', results=results, batch_name=batch_name,
                    upload_summary=upload_summary)

    except Exception as e:
        update_task(task_id, status='error', error=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        cleanup_task(task_id, delay=600)


@app.route('/api/upload', methods=['POST'])
def upload_files():
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files provided'}), 400

    batch_name = request.form.get('batch_name', datetime.now().strftime('%Y%m%d_%H%M%S'))
    task_id = create_task()
    update_task(task_id, phase='Saving uploaded files to server...', batch_name=batch_name)

    tmp_dir = tempfile.mkdtemp(dir=UPLOAD_FOLDER)
    groups = {}
    total_files_received = len(files)
    skipped_non_csv = []
    all_csv_files = []

    for f in files:
        if not f.filename:
            continue
        basename = os.path.basename(f.filename)
        if not basename.lower().endswith('.csv'):
            skipped_non_csv.append(basename)
            continue
        all_csv_files.append(basename)
        filepath = os.path.join(tmp_dir, basename)
        f.save(filepath)
        group_key, chunk_num = get_group_key(basename)
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append((filepath, chunk_num))

    if not groups:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({'error': 'No valid CSV files found'}), 400

    # Pass file stats to background thread
    file_stats = {
        'total_files_received': total_files_received,
        'csv_files': len(all_csv_files),
        'non_csv_skipped': skipped_non_csv,
        'group_file_map': {k: sorted([os.path.basename(fp) for fp, _ in v]) for k, v in groups.items()},
    }

    thread = threading.Thread(target=_background_process,
                              args=(task_id, tmp_dir, groups, batch_name, file_stats), daemon=True)
    thread.start()
    return jsonify({'task_id': task_id, 'total_groups': len(groups)})


@app.route('/api/upload/progress/<task_id>', methods=['GET'])
def upload_progress(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)


@app.route('/api/datasets', methods=['GET'])
def list_datasets():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, batch_name, row_count, col_count, time_min_str, time_max_str, "
        "time_min_seconds, time_max_seconds, source_files, created_at "
        "FROM datasets ORDER BY batch_name, name"
    ).fetchall()
    conn.close()

    datasets = []
    for r in rows:
        sf = None
        try:
            sf = json.loads(r['source_files']) if r['source_files'] else None
        except Exception:
            pass
        datasets.append({
            'id': r['id'],
            'name': r['name'],
            'batch_name': r['batch_name'],
            'row_count': r['row_count'],
            'col_count': r['col_count'],
            'time_min_str': r['time_min_str'],
            'time_max_str': r['time_max_str'],
            'time_min_seconds': r['time_min_seconds'],
            'time_max_seconds': r['time_max_seconds'],
            'source_files': sf,
            'created_at': r['created_at']
        })

    return jsonify(datasets)


@app.route('/api/datasets/<int:dataset_id>/columns', methods=['GET'])
def get_columns(dataset_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT col_index, original_name, display_name, col_type FROM dataset_columns WHERE dataset_id = ? ORDER BY col_index",
        (dataset_id,)
    ).fetchall()
    conn.close()
    return jsonify([{
        'index': r['col_index'],
        'original_name': r['original_name'],
        'display_name': r['display_name'],
        'type': r['col_type']
    } for r in rows])


@app.route('/api/datasets/<int:dataset_id>/data', methods=['GET'])
def get_data(dataset_id):
    conn = get_db()
    ds = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not ds:
        conn.close()
        return jsonify({'error': 'Dataset not found'}), 404

    col_indices_str = request.args.get('columns', '')
    all_cols = conn.execute(
        "SELECT col_index, display_name, col_type FROM dataset_columns WHERE dataset_id = ? ORDER BY col_index",
        (dataset_id,)
    ).fetchall()

    if col_indices_str:
        requested_indices = set(int(x) for x in col_indices_str.split(',') if x.strip())
        selected_cols = [c for c in all_cols if c['col_index'] in requested_indices]
    else:
        selected_cols = list(all_cols)

    table_name = f"data_{dataset_id}"
    select_parts = ["time_str", "time_seconds"]
    for c in selected_cols:
        select_parts.append(f"c{c['col_index']}")

    where_parts = []
    params = []

    time_min = request.args.get('time_min', type=float)
    time_max = request.args.get('time_max', type=float)
    if time_min is not None:
        where_parts.append("time_seconds >= ?")
        params.append(time_min)
    if time_max is not None:
        where_parts.append("time_seconds <= ?")
        params.append(time_max)

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    downsample = request.args.get('downsample', type=int)
    limit = request.args.get('limit', default=50000, type=int)
    offset = request.args.get('offset', default=0, type=int)

    if downsample:
        count_sql = f"SELECT COUNT(*) FROM [{table_name}]{where_clause}"
        total_count = conn.execute(count_sql, params).fetchone()[0]
        if total_count > downsample:
            step = total_count // downsample
            sql = f"SELECT {', '.join(select_parts)} FROM [{table_name}]{where_clause} ORDER BY time_seconds"
            rows = conn.execute(sql, params).fetchall()
            rows = rows[::step][:downsample]
        else:
            sql = f"SELECT {', '.join(select_parts)} FROM [{table_name}]{where_clause} ORDER BY time_seconds"
            rows = conn.execute(sql, params).fetchall()
        total_count_filtered = total_count
    else:
        count_sql = f"SELECT COUNT(*) FROM [{table_name}]{where_clause}"
        total_count_filtered = conn.execute(count_sql, params).fetchone()[0]
        sql = f"SELECT {', '.join(select_parts)} FROM [{table_name}]{where_clause} ORDER BY time_seconds LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()

    conn.close()

    col_meta = [{'display_name': c['display_name'], 'type': c['col_type'], 'index': c['col_index']} for c in selected_cols]
    data = {
        'time_str': [], 'time_seconds': [],
        'columns': col_meta,
        'values': {c['display_name']: [] for c in selected_cols},
        'total_rows': total_count_filtered,
        'returned_rows': len(rows)
    }
    for row in rows:
        data['time_str'].append(row[0])
        data['time_seconds'].append(row[1])
        for i, c in enumerate(selected_cols):
            data['values'][c['display_name']].append(row[2 + i])

    return jsonify(data)


@app.route('/api/datasets/<int:dataset_id>/export', methods=['GET'])
def export_data(dataset_id):
    conn = get_db()
    ds = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not ds:
        conn.close()
        return jsonify({'error': 'Dataset not found'}), 404

    col_indices_str = request.args.get('columns', '')
    all_cols = conn.execute(
        "SELECT col_index, original_name, display_name, col_type FROM dataset_columns WHERE dataset_id = ? ORDER BY col_index",
        (dataset_id,)
    ).fetchall()

    if col_indices_str:
        requested_indices = set(int(x) for x in col_indices_str.split(',') if x.strip())
        selected_cols = [c for c in all_cols if c['col_index'] in requested_indices]
    else:
        selected_cols = list(all_cols)

    table_name = f"data_{dataset_id}"
    select_parts = ["time_str", "time_seconds"]
    for c in selected_cols:
        select_parts.append(f"c{c['col_index']}")

    where_parts = []
    params = []
    time_min = request.args.get('time_min', type=float)
    time_max = request.args.get('time_max', type=float)
    if time_min is not None:
        where_parts.append("time_seconds >= ?")
        params.append(time_min)
    if time_max is not None:
        where_parts.append("time_seconds <= ?")
        params.append(time_max)

    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = f"SELECT {', '.join(select_parts)} FROM [{table_name}]{where_clause} ORDER BY time_seconds"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    header = ["T'(HH:MM:SS.ms)", "T'(seconds)"]
    for c in selected_cols:
        header.append(c['display_name'])
    writer.writerow(header)

    for row in rows:
        csv_row = []
        for i, val in enumerate(row):
            if val is None:
                csv_row.append('')
            elif i == 0:
                csv_row.append('\t' + str(val))
            elif isinstance(val, float):
                if i == 1:
                    csv_row.append(f"{val:.2f}")
                else:
                    csv_row.append(str(int(val)) if val == int(val) else str(val))
            else:
                csv_row.append(str(val))
        writer.writerow(csv_row)

    output.seek(0)
    filename = f"{ds['name']}_export.csv"
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/api/datasets/<int:dataset_id>', methods=['DELETE'])
def delete_dataset(dataset_id):
    conn = get_db()
    ds = conn.execute("SELECT name FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if not ds:
        conn.close()
        return jsonify({'error': 'Dataset not found'}), 404
    conn.execute(f"DROP TABLE IF EXISTS [data_{dataset_id}]")
    conn.execute("DELETE FROM dataset_columns WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Dataset {ds["name"]} deleted'})


@app.route('/api/batches/<batch_name>', methods=['DELETE'])
def delete_batch(batch_name):
    conn = get_db()
    datasets = conn.execute("SELECT id FROM datasets WHERE batch_name = ?", (batch_name,)).fetchall()
    for ds in datasets:
        conn.execute(f"DROP TABLE IF EXISTS [data_{ds['id']}]")
        conn.execute("DELETE FROM dataset_columns WHERE dataset_id = ?", (ds['id'],))
    conn.execute("DELETE FROM datasets WHERE batch_name = ?", (batch_name,))
    conn.execute("DELETE FROM analyses WHERE batch_name = ?", (batch_name,))
    conn.commit()
    conn.close()
    return jsonify({'message': f'Batch {batch_name} deleted ({len(datasets)} datasets)'})


@app.route('/api/analyses/<batch_name>', methods=['GET'])
def get_analysis(batch_name):
    conn = get_db()
    row = conn.execute("SELECT result FROM analyses WHERE batch_name = ?", (batch_name,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'No analysis found'}), 404
    return Response(row['result'], mimetype='application/json')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
