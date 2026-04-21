# -*- coding: utf-8 -*-
"""Phase 1b 迁移 dry-run 工具。

用途：
    在真正让 `init_db` 执行拆表前，先扫描 SQLite 数据库里的
    `event_analysis_tasks` 行，按 `rule_template` 把每条记录映射到未来的
    `fms_event_analysis_tasks` / `fcc_event_analysis_tasks`，并打印汇总。

    不做任何写操作；安全重复运行。

用法（默认读取 backend/data/tsn.db）::

    python scripts/phase1b_migration_dryrun.py
    python scripts/phase1b_migration_dryrun.py --db path/to/other.db

退出码：
    0 = 扫描成功（可能有 WARN 行，但不是致命）
    1 = 数据库或表缺失等致命错误
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tsn.db"


def _tables_present(con: sqlite3.Connection) -> Dict[str, bool]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    return {
        "event_analysis_tasks": "event_analysis_tasks" in names,
        "event_check_results": "event_check_results" in names,
        "event_timeline_events": "event_timeline_events" in names,
        "fms_event_analysis_tasks": "fms_event_analysis_tasks" in names,
        "fcc_event_analysis_tasks": "fcc_event_analysis_tasks" in names,
        "event_analysis_tasks__legacy": "event_analysis_tasks__legacy" in names,
    }


def _count_by_rule_template(con: sqlite3.Connection) -> Dict[str, int]:
    try:
        rows = con.execute(
            "SELECT COALESCE(rule_template,'(null)') AS rt, COUNT(*) "
            "FROM event_analysis_tasks GROUP BY rt"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"[dryrun] 读取 event_analysis_tasks 失败: {exc}")
        return {}
    return {r[0]: int(r[1]) for r in rows}


def _child_counts(con: sqlite3.Connection) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in ("event_check_results", "event_timeline_events"):
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        out[t] = int(n)
    return out


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Phase 1b 拆表 dry-run")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 文件路径（默认 {DEFAULT_DB_PATH}）",
    )
    args = parser.parse_args(argv)

    db_path: Path = args.db
    if not db_path.is_file():
        print(f"[dryrun] 找不到数据库：{db_path}")
        return 1

    con = sqlite3.connect(str(db_path))
    try:
        flags = _tables_present(con)
        print(f"[dryrun] 数据库: {db_path} ({os.path.getsize(db_path)} 字节)")
        print("[dryrun] 表存在性：")
        for k, v in flags.items():
            print(f"    {'✓' if v else '✗'} {k}")

        if flags["event_analysis_tasks__legacy"] and not flags["event_analysis_tasks"]:
            print("[dryrun] 迁移已完成（旧表已改名 __legacy）。无需再跑。")
            return 0

        if not flags["event_analysis_tasks"]:
            print("[dryrun] 旧表 event_analysis_tasks 不存在，可能是全新部署。跳过。")
            return 0

        counts = _count_by_rule_template(con)
        total = sum(counts.values())
        fcc = counts.get("fcc_v1", 0)
        # 迁移规则（见 database._split_event_analysis_tables）：
        #   rule_template == 'fcc_v1' → fcc_event_analysis_tasks
        #   其余一切（含 fms_v1/default_v1/NULL） → fms_event_analysis_tasks
        fms = total - fcc

        print(f"[dryrun] event_analysis_tasks 共 {total} 行，按 rule_template 分布：")
        for rt, n in sorted(counts.items()):
            print(f"    rule_template={rt!s:<12} -> {n} 行")

        child = _child_counts(con)
        print(f"[dryrun] event_check_results={child['event_check_results']} 行，"
              f"event_timeline_events={child['event_timeline_events']} 行")

        print("[dryrun] 预期迁移结果（按 init_db 里实际分流规则）：")
        print(f"    fms_event_analysis_tasks  ← (非 fcc_v1)   {fms} 行")
        print(f"    fcc_event_analysis_tasks  ← fcc_v1        {fcc} 行")
        non_standard = [rt for rt in counts if rt not in ("fms_v1", "fcc_v1")]
        if non_standard:
            joined = ", ".join(f"{rt}({counts[rt]})" for rt in non_standard)
            print(
                "    [INFO] 非标准 rule_template: "
                + joined
                + " -- 会按『非 fcc_v1 归 FMS』规则合入 fms_event_analysis_tasks。"
            )

        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
