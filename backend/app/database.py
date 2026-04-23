# -*- coding: utf-8 -*-
"""数据库配置"""
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from .config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)


# SQLite 并发优化：每次建立连接时打开 WAL + 等锁 30s + 适度放松 fsync。
# - journal_mode=WAL: 允许"一读多写"真正并发, 避免 "database is locked"
# - synchronous=NORMAL: WAL 模式下 fsync 频率降低, 写吞吐显著提升, 断电最多丢失最近一次事务
# - busy_timeout=30000: 拿锁冲突时 SQLite 内部最多等 30s, 而不是立刻报错
# - temp_store=MEMORY: 临时表/索引放内存, 小代价换速度
# - mmap_size=256MB: 允许用 mmap 读文件, 大查询更快
# 只对底层 sqlite 驱动生效；非 sqlite 后端请删掉此钩子。
@event.listens_for(engine.sync_engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256 MB
    finally:
        cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    """获取数据库会话"""
    async with async_session() as session:
        yield session


async def init_db():
    """初始化数据库（自动添加缺失列）"""
    from sqlalchemy import inspect, text
    
    async with engine.begin() as conn:
        # 先创建所有缺失的表
        await conn.run_sync(Base.metadata.create_all)
        
        # 检查并添加缺失的列（新增字段迁移）
        def _check_and_add_columns(sync_conn):
            inspector = inspect(sync_conn)
            
            # parse_tasks 表迁移 - 需要重建表以支持 parser_profile_id 为 NULL
            if 'parse_tasks' in inspector.get_table_names():
                # 使用 PRAGMA 检查表结构中 parser_profile_id 是否 NOT NULL
                result = sync_conn.execute(text("PRAGMA table_info(parse_tasks)"))
                columns_info = {row[1]: row for row in result.fetchall()}
                
                needs_rebuild = False
                if 'parser_profile_id' in columns_info:
                    # row[3] 是 notnull 标志, 1 = NOT NULL, 0 = 可为空
                    if columns_info['parser_profile_id'][3] == 1:
                        needs_rebuild = True
                
                existing_cols = set(columns_info.keys())
                cols_to_add = {
                    'protocol_version_id': 'INTEGER REFERENCES protocol_versions(id)',
                    'parser_profile_ids': 'JSON',
                    'device_parser_map': 'JSON',
                    'selected_ports': 'JSON',
                    'selected_devices': 'JSON',
                    'progress': 'INTEGER DEFAULT 0',
                    # 任务中心增强字段
                    'display_name': 'VARCHAR(255)',
                    'tags': 'JSON',
                    'file_size': 'INTEGER',
                    'stage': 'VARCHAR(50)',
                    'cancel_requested': 'INTEGER DEFAULT 0',
                    'started_at': 'DATETIME',
                    # 设备协议版本映射（TSN 对齐：用户上传时选择的 device_protocol_version）
                    'device_protocol_version_map': 'JSON',
                }
                for col_name, col_type in cols_to_add.items():
                    if col_name not in existing_cols:
                        sync_conn.execute(
                            text(f"ALTER TABLE parse_tasks ADD COLUMN {col_name} {col_type}")
                        )
                        print(f"[DB] 已添加 parse_tasks.{col_name} 列")

                
                if needs_rebuild:
                    print("[DB] 需要重建 parse_tasks 表以支持 parser_profile_id 为 NULL...")
                    sync_conn.execute(text("DROP TABLE IF EXISTS parse_tasks_new"))
                    sync_conn.execute(text("""
                        CREATE TABLE parse_tasks_new (
                            id INTEGER PRIMARY KEY,
                            filename VARCHAR(255) NOT NULL,
                            file_path VARCHAR(500) NOT NULL,
                            parser_profile_id INTEGER REFERENCES parser_profiles(id),
                            parser_profile_ids JSON,
                            device_parser_map JSON,
                            protocol_version_id INTEGER REFERENCES protocol_versions(id),
                            status VARCHAR(20) DEFAULT 'pending',
                            selected_ports JSON,
                            selected_devices JSON,
                            total_packets INTEGER DEFAULT 0,
                            parsed_packets INTEGER DEFAULT 0,
                            progress INTEGER DEFAULT 0,
                            error_message TEXT,
                            created_at DATETIME,
                            completed_at DATETIME
                        )
                    """))
                    device_parser_map_expr = "device_parser_map" if "device_parser_map" in columns_info else "NULL"
                    sync_conn.execute(text(f"""
                        INSERT INTO parse_tasks_new (
                            id, filename, file_path, parser_profile_id, parser_profile_ids,
                            device_parser_map, protocol_version_id, status, selected_ports, selected_devices,
                            total_packets, parsed_packets, progress, error_message, created_at, completed_at
                        )
                        SELECT
                            id, filename, file_path, parser_profile_id, parser_profile_ids,
                            {device_parser_map_expr}, protocol_version_id, status, selected_ports, selected_devices,
                            total_packets, parsed_packets, 0, error_message, created_at, completed_at
                        FROM parse_tasks
                    """))
                    sync_conn.execute(text("DROP TABLE parse_tasks"))
                    sync_conn.execute(text("ALTER TABLE parse_tasks_new RENAME TO parse_tasks"))
                    print("[DB] 已重建 parse_tasks 表，parser_profile_id 现在可以为空")
            
            # parse_results 表迁移
            if 'parse_results' in inspector.get_table_names():
                columns = [col['name'] for col in inspector.get_columns('parse_results')]
                
                if 'parser_profile_id' not in columns:
                    sync_conn.execute(
                        text("ALTER TABLE parse_results ADD COLUMN parser_profile_id INTEGER REFERENCES parser_profiles(id)")
                    )
                    print("[DB] 已添加 parse_results.parser_profile_id 列")
                
                if 'parser_profile_name' not in columns:
                    sync_conn.execute(
                        text("ALTER TABLE parse_results ADD COLUMN parser_profile_name VARCHAR(100)")
                    )
                    print("[DB] 已添加 parse_results.parser_profile_name 列")
                
                if 'source_device' not in columns:
                    sync_conn.execute(
                        text("ALTER TABLE parse_results ADD COLUMN source_device VARCHAR(100)")
                    )
                    print("[DB] 已添加 parse_results.source_device 列")
            
            # parser_profiles 表迁移
            if 'parser_profiles' in inspector.get_table_names():
                pp_columns = [col['name'] for col in inspector.get_columns('parser_profiles')]
                if 'protocol_family' not in pp_columns:
                    sync_conn.execute(
                        text("ALTER TABLE parser_profiles ADD COLUMN protocol_family VARCHAR(50)")
                    )
                    print("[DB] 已添加 parser_profiles.protocol_family 列")
                
                sync_conn.execute(
                    text("UPDATE parser_profiles SET protocol_family = 'xpdr' WHERE parser_key LIKE 'jzxpdr113b%' AND (protocol_family IS NULL OR protocol_family = '')")
                )
                sync_conn.execute(
                    text("UPDATE parser_profiles SET protocol_family = 'irs' WHERE parser_key LIKE 'irs%' AND (protocol_family IS NULL OR protocol_family = '')")
                )
                sync_conn.execute(
                    text("UPDATE parser_profiles SET supported_ports = '' WHERE parser_key IN ('jzxpdr113b_v20260113', 'irs_v3') AND supported_ports IS NOT NULL AND supported_ports != ''")
                )
                sync_conn.execute(
                    text("UPDATE parser_profiles SET is_active = 0 WHERE parser_key IN ('jzxpdr113b_7004_v20260113', 'jzxpdr113b_7005_v20260113') AND is_active = 1")
                )
                print("[DB] 已更新解析器配置（protocol_family + 动态端口 + 停用旧解析器）")

            # shared_tsn_files 表迁移：补齐 file_size 列
            if 'shared_tsn_files' in inspector.get_table_names():
                st_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(shared_tsn_files)")).fetchall()}
                if 'file_size' not in st_cols:
                    sync_conn.execute(
                        text("ALTER TABLE shared_tsn_files ADD COLUMN file_size INTEGER")
                    )
                    print("[DB] 已添加 shared_tsn_files.file_size 列")

            # users 表迁移
            if 'users' in inspector.get_table_names():
                user_cols = [col['name'] for col in inspector.get_columns('users')]
                if 'display_name' not in user_cols:
                    sync_conn.execute(
                        text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64)")
                    )
                    print("[DB] 已添加 users.display_name 列")

            # role_port_access 表迁移（角色-端口权限）
            if 'role_port_access' not in inspector.get_table_names():
                sync_conn.execute(text("""
                    CREATE TABLE role_port_access (
                        id INTEGER PRIMARY KEY,
                        role VARCHAR(20) NOT NULL,
                        protocol_version_id INTEGER NOT NULL REFERENCES protocol_versions(id),
                        port_number INTEGER NOT NULL
                    )
                """))
                sync_conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_role_proto_port ON role_port_access(role, protocol_version_id, port_number)")
                )
                sync_conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_role_port_access_role ON role_port_access(role)")
                )
                print("[DB] 已创建 role_port_access 表及索引")

                # JZXPDR113B S模式应答机：平台与库中统一显示为「S模式应答机」（不再带型号/日期后缀）
                sync_conn.execute(
                    text(
                        "UPDATE parser_profiles SET name = 'S模式应答机', version = '' "
                        "WHERE parser_key = 'jzxpdr113b_v20260113'"
                    )
                )
                sync_conn.execute(
                    text(
                        "UPDATE parser_profiles SET name = 'S模式应答机', version = '' "
                        "WHERE name LIKE '%JZXPDR113B%S模式应答机%' AND parser_key != 'jzxpdr113b_v20260113'"
                    )
                )
                if 'parse_tasks' in inspector.get_table_names():
                    pt_cols = [row[1] for row in sync_conn.execute(text("PRAGMA table_info(parse_tasks)")).fetchall()]
                    if 'device_parser_map' in pt_cols:
                        for old, new in (
                            ('JZXPDR113B S模式应答机 20260113', 'S模式应答机'),
                            ('JZXPDR113B S模式应答机', 'S模式应答机'),
                        ):
                            sync_conn.execute(
                                text(
                                    "UPDATE parse_tasks SET device_parser_map = REPLACE(device_parser_map, :o, :n) "
                                    "WHERE device_parser_map LIKE :pat"
                                ),
                                {"o": old, "n": new, "pat": f"%{old}%"},
                            )
                if 'parse_results' in inspector.get_table_names():
                    pr_cols = [c['name'] for c in inspector.get_columns('parse_results')]
                    if 'parser_profile_name' in pr_cols:
                        sync_conn.execute(
                            text(
                                "UPDATE parse_results SET parser_profile_name = 'S模式应答机' "
                                "WHERE parser_profile_name LIKE '%JZXPDR113B%S模式应答机%' "
                                "OR parser_profile_name = 'JZXPDR113B S模式应答机 20260113'"
                            )
                        )
                    if 'message_name' in pr_cols:
                        for old, new in (
                            ('JZXPDR113B S模式应答机 20260113', 'S模式应答机'),
                            ('JZXPDR113B S模式应答机', 'S模式应答机'),
                        ):
                            sync_conn.execute(
                                text(
                                    "UPDATE parse_results SET message_name = REPLACE(message_name, :o, :n) "
                                    "WHERE message_name LIKE :pat"
                                ),
                                {"o": old, "n": new, "pat": f"%{old}%"},
                            )
                print("[DB] 已统一 S模式应答机 显示名称（parser_profiles、parse_results、device_parser_map）")

            # event_analysis_tasks：独立事件分析（parse_task_id 可空 + pcap 路径）
            # Phase 1b 之前的旧表维护逻辑：仅在旧表还存在时做原地补列
            if 'event_analysis_tasks' in inspector.get_table_names():
                ea_cols = list(sync_conn.execute(text("PRAGMA table_info(event_analysis_tasks)")).fetchall())
                ea_col_names = {row[1] for row in ea_cols}
                parse_info = next((r for r in ea_cols if r[1] == 'parse_task_id'), None)

                if parse_info is not None and parse_info[3] == 1:
                    print("[DB] 重建 event_analysis_tasks 以支持独立 pcap 事件分析（parse_task_id 可空）...")
                    sync_conn.execute(text("PRAGMA foreign_keys=OFF"))
                    sync_conn.execute(text("ALTER TABLE event_analysis_tasks RENAME TO event_analysis_tasks_old"))
                    sync_conn.execute(text("""
                        CREATE TABLE event_analysis_tasks (
                            id INTEGER PRIMARY KEY,
                            parse_task_id INTEGER REFERENCES parse_tasks(id),
                            pcap_filename VARCHAR(200),
                            pcap_file_path VARCHAR(500),
                            name VARCHAR(200),
                            rule_template VARCHAR(100),
                            status VARCHAR(20),
                            error_message TEXT,
                            total_checks INTEGER DEFAULT 0,
                            passed_checks INTEGER DEFAULT 0,
                            failed_checks INTEGER DEFAULT 0,
                            created_at DATETIME,
                            completed_at DATETIME
                        )
                    """))
                    sync_conn.execute(text("""
                        INSERT INTO event_analysis_tasks (
                            id, parse_task_id, pcap_filename, pcap_file_path, name, rule_template,
                            status, error_message, total_checks, passed_checks, failed_checks,
                            created_at, completed_at
                        )
                        SELECT
                            id, parse_task_id, NULL, NULL, name, rule_template,
                            status, error_message, total_checks, passed_checks, failed_checks,
                            created_at, completed_at
                        FROM event_analysis_tasks_old
                    """))
                    sync_conn.execute(text("DROP TABLE event_analysis_tasks_old"))
                    sync_conn.execute(text("PRAGMA foreign_keys=ON"))
                    print("[DB] event_analysis_tasks 已重建")
                else:
                    if 'pcap_filename' not in ea_col_names:
                        sync_conn.execute(
                            text("ALTER TABLE event_analysis_tasks ADD COLUMN pcap_filename VARCHAR(200)")
                        )
                        print("[DB] 已添加 event_analysis_tasks.pcap_filename")
                    if 'pcap_file_path' not in ea_col_names:
                        sync_conn.execute(
                            text("ALTER TABLE event_analysis_tasks ADD COLUMN pcap_file_path VARCHAR(500)")
                        )
                        print("[DB] 已添加 event_analysis_tasks.pcap_file_path")
                    if 'progress' not in ea_col_names:
                        sync_conn.execute(
                            text("ALTER TABLE event_analysis_tasks ADD COLUMN progress INTEGER DEFAULT 0")
                        )
                        print("[DB] 已添加 event_analysis_tasks.progress")

            # event_analysis_tasks / compare_tasks：MR4 Bundle 版本锁定列
            if 'event_analysis_tasks' in inspector.get_table_names():
                ea_cols2 = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(event_analysis_tasks)")).fetchall()}
                if 'bundle_version_id' not in ea_cols2:
                    sync_conn.execute(text(
                        "ALTER TABLE event_analysis_tasks ADD COLUMN bundle_version_id INTEGER "
                        "REFERENCES protocol_versions(id)"
                    ))
                    print("[DB] 已添加 event_analysis_tasks.bundle_version_id")

            # ── Phase 1b 拆表：event_analysis_tasks → fms_* + fcc_* ──
            # 触发条件：旧表还存在 + 没被标记为 legacy；新表由 Base.metadata.create_all 建出
            tables_now = set(inspector.get_table_names())
            if (
                'event_analysis_tasks' in tables_now
                and 'event_analysis_tasks__legacy' not in tables_now
            ):
                try:
                    _split_event_analysis_tables(sync_conn)
                except Exception as exc:
                    print(f"[DB] Phase 1b 拆表失败，已回滚： {exc}")
                    raise

            if 'compare_tasks' in inspector.get_table_names():
                ct_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(compare_tasks)")).fetchall()}
                if 'bundle_version_id' not in ct_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE compare_tasks ADD COLUMN bundle_version_id INTEGER "
                        "REFERENCES protocol_versions(id)"
                    ))
                    print("[DB] 已添加 compare_tasks.bundle_version_id")

            # 飞控事件分析与 TSN 事件分析共用 event_analysis_tasks 表，已有列；
            # 自动飞行性能分析使用独立表 auto_flight_analysis_tasks，需要补列
            if 'auto_flight_analysis_tasks' in inspector.get_table_names():
                af_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(auto_flight_analysis_tasks)")).fetchall()}
                if 'bundle_version_id' not in af_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE auto_flight_analysis_tasks ADD COLUMN bundle_version_id INTEGER "
                        "REFERENCES protocol_versions(id)"
                    ))
                    print("[DB] 已添加 auto_flight_analysis_tasks.bundle_version_id")

            # protocol_versions 表迁移：版本生命周期状态
            if 'protocol_versions' in inspector.get_table_names():
                pv_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(protocol_versions)")).fetchall()}
                pv_add = {
                    'availability_status': "VARCHAR(20) NOT NULL DEFAULT 'Available'",
                    'activated_at': 'DATETIME',
                    'activated_by': 'VARCHAR(64)',
                    'forced_activation': 'BOOLEAN NOT NULL DEFAULT 0',
                    # MR3 激活闸门扩展列
                    'activation_report_json': 'TEXT',
                    'activation_report_generated_at': 'DATETIME',
                    'generated_artifacts_json': 'TEXT',
                    'activation_force_reason': 'TEXT',
                }
                for col_name, col_type in pv_add.items():
                    if col_name not in pv_cols:
                        sync_conn.execute(
                            text(f"ALTER TABLE protocol_versions ADD COLUMN {col_name} {col_type}")
                        )
                        print(f"[DB] 已添加 protocol_versions.{col_name} 列")
                # 历史版本一律视为已可用
                sync_conn.execute(
                    text(
                        "UPDATE protocol_versions SET availability_status='Available' "
                        "WHERE availability_status IS NULL OR availability_status=''"
                    )
                )

            # port_definitions 表迁移：端口协议族（权威列），并按 PORT_FAMILY_MAP 回填
            if 'port_definitions' in inspector.get_table_names():
                pd_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(port_definitions)")).fetchall()}
                if 'protocol_family' not in pd_cols:
                    sync_conn.execute(
                        text("ALTER TABLE port_definitions ADD COLUMN protocol_family VARCHAR(50)")
                    )
                    print("[DB] 已添加 port_definitions.protocol_family 列")

                # ICD 6.0.x 扩展列
                icd_cols_ext = {
                    'message_id': 'VARCHAR(64)',
                    'source_interface_id': 'VARCHAR(64)',
                    'port_id_label': 'VARCHAR(64)',
                    'diu_id': 'VARCHAR(64)',
                    'diu_id_set': 'VARCHAR(200)',
                    'diu_recv_mode': 'VARCHAR(100)',
                    'tsn_source_ip': 'VARCHAR(100)',
                    'diu_ip': 'VARCHAR(100)',
                    'dataset_path': 'VARCHAR(200)',
                    'data_real_path': 'VARCHAR(200)',
                    'final_recv_device': 'VARCHAR(100)',
                }
                for col_name, col_type in icd_cols_ext.items():
                    if col_name not in pd_cols:
                        sync_conn.execute(
                            text(f"ALTER TABLE port_definitions ADD COLUMN {col_name} {col_type}")
                        )
                        print(f"[DB] 已添加 port_definitions.{col_name} 列（ICD 扩展）")

                # port_role：端口角色（Phase 2 新增，ICD 维度）
                if 'port_role' not in pd_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE port_definitions ADD COLUMN port_role VARCHAR(50)"
                    ))
                    print("[DB] 已添加 port_definitions.port_role 列")

                # 延迟导入以避免循环依赖
                try:
                    from .services.protocol_service import PORT_FAMILY_MAP  # type: ignore
                except Exception:
                    PORT_FAMILY_MAP = {}
                if PORT_FAMILY_MAP:
                    backfill = 0
                    for port_num, family in PORT_FAMILY_MAP.items():
                        res = sync_conn.execute(
                            text(
                                "UPDATE port_definitions SET protocol_family=:f "
                                "WHERE port_number=:p AND (protocol_family IS NULL OR protocol_family='')"
                            ),
                            {"f": family, "p": int(port_num)},
                        )
                        backfill += res.rowcount or 0
                    if backfill:
                        print(f"[DB] 已按 PORT_FAMILY_MAP 回填 port_definitions.protocol_family ({backfill} 行)")

                # port_role 回填：按 message_name 关键字推断一次（仅对空值）
                role_rules = [
                    ("fcc_event",   "%FCC%"),
                    ("fcc_event",   "%飞控%"),
                    ("auto_flight", "%AFCS%"),
                    ("auto_flight", "%自动飞行%"),
                    ("auto_flight", "%自主飞行%"),
                    ("fms_event",   "%FMS%"),
                    ("fms_event",   "%飞管%"),
                    ("tsn_anomaly", "%"),
                ]
                total_role_backfill = 0
                for role, pattern in role_rules:
                    if pattern == "%":
                        # 兜底：剩余尚未分类的端口默认归 tsn_anomaly
                        res = sync_conn.execute(text(
                            "UPDATE port_definitions SET port_role=:r "
                            "WHERE port_role IS NULL OR port_role=''"
                        ), {"r": role})
                    else:
                        res = sync_conn.execute(text(
                            "UPDATE port_definitions SET port_role=:r "
                            "WHERE (port_role IS NULL OR port_role='') AND "
                            "      (message_name LIKE :p OR description LIKE :p)"
                        ), {"r": role, "p": pattern})
                    total_role_backfill += res.rowcount or 0
                if total_role_backfill:
                    print(f"[DB] 已按 message_name/description 回填 port_definitions.port_role ({total_role_backfill} 行)")

                # Phase C：在 fcc_event 聚合角色之上，按默认端口号号段进一步细分：
                #   9001-9009 → fcc_status, 9011-9019 → fcc_channel, 9021-9029 → fcc_fault
                # IRS 端口（1001-1003）→ irs_input（供自动飞行分析 bundle 驱动）
                # 只覆盖当前被回填为 fcc_event / tsn_anomaly / 空值 的行，手工设定过的细粒度 role 保持不变。
                fine_rules = [
                    ("fcc_status",  "port_number BETWEEN 9001 AND 9009"),
                    ("fcc_channel", "port_number BETWEEN 9011 AND 9019"),
                    ("fcc_fault",   "port_number BETWEEN 9021 AND 9029"),
                    ("irs_input",   "port_number BETWEEN 1001 AND 1003"),
                ]
                fine_total = 0
                for role, condition in fine_rules:
                    res = sync_conn.execute(text(
                        "UPDATE port_definitions SET port_role=:r "
                        f"WHERE {condition} AND "
                        "      (port_role IS NULL OR port_role='' "
                        "       OR port_role IN ('fcc_event','tsn_anomaly','other'))"
                    ), {"r": role})
                    fine_total += res.rowcount or 0
                if fine_total:
                    print(f"[DB] 已按默认端口号细分 FCC/IRS port_role ({fine_total} 行)")

            # protocol_version_drafts：索引 + 半开唯一约束（每个 base_version 同时最多一个 pending CR）
            if 'protocol_version_drafts' in inspector.get_table_names():
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_draft_status "
                        "ON protocol_version_drafts(status)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_draft_created_by "
                        "ON protocol_version_drafts(created_by)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_draft_pending_per_base "
                        "ON protocol_version_drafts(base_version_id) "
                        "WHERE status='pending' AND base_version_id IS NOT NULL"
                    )
                )
            if 'draft_port_definitions' in inspector.get_table_names():
                sync_conn.execute(text("DROP INDEX IF EXISTS uq_draft_port"))
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_draft_port_draft "
                        "ON draft_port_definitions(draft_id, port_number)"
                    )
                )
                # ICD 6.0.x 扩展列（与 port_definitions 保持一致）
                dp_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(draft_port_definitions)")).fetchall()}
                draft_icd_ext = {
                    'message_id': 'VARCHAR(64)',
                    'source_interface_id': 'VARCHAR(64)',
                    'port_id_label': 'VARCHAR(64)',
                    'diu_id': 'VARCHAR(64)',
                    'diu_id_set': 'VARCHAR(200)',
                    'diu_recv_mode': 'VARCHAR(100)',
                    'tsn_source_ip': 'VARCHAR(100)',
                    'diu_ip': 'VARCHAR(100)',
                    'dataset_path': 'VARCHAR(200)',
                    'data_real_path': 'VARCHAR(200)',
                    'final_recv_device': 'VARCHAR(100)',
                }
                for col_name, col_type in draft_icd_ext.items():
                    if col_name not in dp_cols:
                        sync_conn.execute(
                            text(f"ALTER TABLE draft_port_definitions ADD COLUMN {col_name} {col_type}")
                        )
                        print(f"[DB] 已添加 draft_port_definitions.{col_name} 列（ICD 扩展）")

                if 'port_role' not in dp_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE draft_port_definitions ADD COLUMN port_role VARCHAR(50)"
                    ))
                    print("[DB] 已添加 draft_port_definitions.port_role 列")
            if 'draft_field_definitions' in inspector.get_table_names():
                sync_conn.execute(text("DROP INDEX IF EXISTS uq_draft_field"))
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_draft_field_port "
                        "ON draft_field_definitions(draft_port_id)"
                    )
                )
            if 'protocol_change_requests' in inspector.get_table_names():
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_cr_overall_status "
                        "ON protocol_change_requests(overall_status)"
                    )
                )
                # 设备协议集成：补齐 draft_kind / device_draft_id 列 + 回填
                cr_cols_info = {
                    row[1]: row
                    for row in sync_conn.execute(
                        text("PRAGMA table_info(protocol_change_requests)")
                    ).fetchall()
                }
                cr_cols = set(cr_cols_info.keys())
                if 'draft_kind' not in cr_cols:
                    sync_conn.execute(
                        text(
                            "ALTER TABLE protocol_change_requests ADD COLUMN "
                            "draft_kind VARCHAR(40) NOT NULL DEFAULT 'tsn_network'"
                        )
                    )
                    print("[DB] 已添加 protocol_change_requests.draft_kind 列")
                if 'device_draft_id' not in cr_cols:
                    sync_conn.execute(
                        text(
                            "ALTER TABLE protocol_change_requests ADD COLUMN "
                            "device_draft_id INTEGER"
                        )
                    )
                    print("[DB] 已添加 protocol_change_requests.device_draft_id 列")
                # draft_id 早期是 NOT NULL（仅 TSN 场景）；现在设备协议场景为 NULL，
                # 需要重建表放宽 NOT NULL 约束。SQLite 不支持 ALTER COLUMN DROP NOT NULL。
                draft_id_col = cr_cols_info.get('draft_id')
                if draft_id_col is not None and draft_id_col[3] == 1:
                    print("[DB] 重建 protocol_change_requests 以允许 draft_id 为 NULL ...")
                    # 重新读一次所有列，兼容刚 ADD COLUMN 的新字段
                    fresh_cols = [
                        row[1]
                        for row in sync_conn.execute(
                            text("PRAGMA table_info(protocol_change_requests)")
                        ).fetchall()
                    ]
                    sync_conn.execute(text("DROP TABLE IF EXISTS protocol_change_requests_new"))
                    # 注：不恢复 submit_note 字段（模型在 draft 上），submit_note / published_* 等字段
                    # 历史上就不存在于该表，保持原语义。
                    sync_conn.execute(
                        text(
                            """
                            CREATE TABLE protocol_change_requests_new (
                                id INTEGER PRIMARY KEY,
                                draft_id INTEGER REFERENCES protocol_version_drafts(id),
                                device_draft_id INTEGER REFERENCES device_protocol_drafts(id),
                                draft_kind VARCHAR(40) NOT NULL DEFAULT 'tsn_network',
                                submitted_by VARCHAR(64),
                                submitted_at DATETIME,
                                current_step INTEGER NOT NULL DEFAULT 0,
                                overall_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                                diff_summary JSON,
                                final_note TEXT
                            )
                            """
                        )
                    )
                    # 动态拼列名（只迁移同时存在于新旧表的字段）
                    new_table_cols = [
                        'id', 'draft_id', 'device_draft_id', 'draft_kind',
                        'submitted_by', 'submitted_at', 'current_step',
                        'overall_status', 'diff_summary', 'final_note',
                    ]
                    shared = [c for c in new_table_cols if c in fresh_cols]
                    col_list = ', '.join(shared)
                    sync_conn.execute(
                        text(
                            f"""
                            INSERT INTO protocol_change_requests_new ({col_list})
                            SELECT {col_list} FROM protocol_change_requests
                            """
                        )
                    )
                    sync_conn.execute(text("DROP TABLE protocol_change_requests"))
                    sync_conn.execute(
                        text(
                            "ALTER TABLE protocol_change_requests_new "
                            "RENAME TO protocol_change_requests"
                        )
                    )
                    # 重建索引
                    sync_conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_cr_draft_id "
                            "ON protocol_change_requests(draft_id)"
                        )
                    )
                    sync_conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_cr_overall_status "
                            "ON protocol_change_requests(overall_status)"
                        )
                    )
                # 存量数据：未标 kind 的默认 tsn_network（TSN 网络配置）
                sync_conn.execute(
                    text(
                        "UPDATE protocol_change_requests SET draft_kind='tsn_network' "
                        "WHERE draft_kind IS NULL OR draft_kind=''"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_cr_draft_kind "
                        "ON protocol_change_requests(draft_kind)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_cr_device_draft_id "
                        "ON protocol_change_requests(device_draft_id)"
                    )
                )

            # ── 设备协议（ARINC429/CAN/RS422）：索引增强 ──
            if 'device_protocol_specs' in inspector.get_table_names():
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_spec_family_ata "
                        "ON device_protocol_specs(protocol_family, ata_code)"
                    )
                )
                # Phase 7：parser_family_hints 字段已下线，迁移脚本不再补列。
                # 老库里可能残留这一列（SQLite 不支持 DROP COLUMN），ORM 不再声明
                # 该属性，相当于只读历史数据，读写路径都不会命中它。
            if 'device_protocol_versions' in inspector.get_table_names():
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_ver_spec_seq "
                        "ON device_protocol_versions(spec_id, version_seq)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_ver_git_status "
                        "ON device_protocol_versions(git_export_status)"
                    )
                )
                # 幂等补列：版本生命周期（forced_activation / activation_report_json / deprecated_*)
                ver_cols = {
                    row[1]
                    for row in sync_conn.execute(
                        text("PRAGMA table_info(device_protocol_versions)")
                    ).fetchall()
                }
                _lifecycle_cols = [
                    ("forced_activation", "BOOLEAN NOT NULL DEFAULT 0"),
                    ("activation_report_json", "JSON"),
                    ("deprecated_at", "DATETIME"),
                    ("deprecated_by", "VARCHAR(64)"),
                    ("deprecation_reason", "TEXT"),
                    # Phase 7：parser_key 下沉到 version（bundle ↔ Python 一对一）
                    ("parser_key", "VARCHAR(100)"),
                ]
                for col_name, col_ddl in _lifecycle_cols:
                    if col_name not in ver_cols:
                        print(f"[DB] ALTER device_protocol_versions ADD COLUMN {col_name}")
                        sync_conn.execute(
                            text(
                                f"ALTER TABLE device_protocol_versions ADD COLUMN {col_name} {col_ddl}"
                            )
                        )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_ver_availability "
                        "ON device_protocol_versions(availability_status)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_ver_parser_key "
                        "ON device_protocol_versions(parser_key)"
                    )
                )
            if 'device_protocol_drafts' in inspector.get_table_names():
                # target_version 早期是 NOT NULL；现在需要可为空（publish 时自动算版本号）
                drf_cols_info = {
                    row[1]: row
                    for row in sync_conn.execute(text("PRAGMA table_info(device_protocol_drafts)")).fetchall()
                }
                target_col = drf_cols_info.get('target_version')
                if target_col is not None and target_col[3] == 1:
                    print("[DB] 重建 device_protocol_drafts 以允许 target_version 为 NULL ...")
                    sync_conn.execute(text("DROP TABLE IF EXISTS device_protocol_drafts_new"))
                    sync_conn.execute(
                        text(
                            """
                            CREATE TABLE device_protocol_drafts_new (
                                id INTEGER PRIMARY KEY,
                                spec_id INTEGER REFERENCES device_protocol_specs(id),
                                base_version_id INTEGER REFERENCES device_protocol_versions(id),
                                protocol_family VARCHAR(50) NOT NULL,
                                source_type VARCHAR(20) NOT NULL,
                                name VARCHAR(200) NOT NULL,
                                target_version VARCHAR(50),
                                description TEXT,
                                spec_json JSON NOT NULL,
                                pending_spec_meta JSON,
                                status VARCHAR(20) NOT NULL,
                                submit_note TEXT,
                                created_by VARCHAR(64),
                                created_at DATETIME,
                                updated_at DATETIME,
                                published_version_id INTEGER REFERENCES device_protocol_versions(id)
                            )
                            """
                        )
                    )
                    sync_conn.execute(
                        text(
                            """
                            INSERT INTO device_protocol_drafts_new
                                (id, spec_id, base_version_id, protocol_family, source_type, name,
                                 target_version, description, spec_json, pending_spec_meta, status,
                                 submit_note, created_by, created_at, updated_at, published_version_id)
                            SELECT id, spec_id, base_version_id, protocol_family, source_type, name,
                                   target_version, description, spec_json, pending_spec_meta, status,
                                   submit_note, created_by, created_at, updated_at, published_version_id
                            FROM device_protocol_drafts
                            """
                        )
                    )
                    sync_conn.execute(text("DROP TABLE device_protocol_drafts"))
                    sync_conn.execute(
                        text("ALTER TABLE device_protocol_drafts_new RENAME TO device_protocol_drafts")
                    )
                    print("[DB] device_protocol_drafts 表已重建")

                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_draft_status "
                        "ON device_protocol_drafts(status)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_dev_draft_created_by "
                        "ON device_protocol_drafts(created_by)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_device_protocol_drafts_spec_id "
                        "ON device_protocol_drafts(spec_id)"
                    )
                )
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_device_protocol_drafts_protocol_family "
                        "ON device_protocol_drafts(protocol_family)"
                    )
                )
                # 旧版只对 pending 互斥；新版：对 draft + pending 同时互斥，保证
                # 每个设备同一时刻只允许一条活动草稿（= 一次修改 → 一次审批）
                sync_conn.execute(
                    text("DROP INDEX IF EXISTS uq_dev_draft_pending_per_spec")
                )
                sync_conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dev_draft_active_per_spec "
                        "ON device_protocol_drafts(spec_id) "
                        "WHERE status IN ('draft','pending') AND spec_id IS NOT NULL"
                    )
                )
            if 'notifications' in inspector.get_table_names():
                sync_conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_notif_user_unread "
                        "ON notifications(username, read_at)"
                    )
                )

            # auto_flight_analysis_tasks：自动飞行性能分析任务（支持 pcap 独立分析 + 解析任务分析）
            if 'auto_flight_analysis_tasks' in inspector.get_table_names():
                af_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(auto_flight_analysis_tasks)")).fetchall()}
                cols_to_add = {
                    'parse_task_id': 'INTEGER REFERENCES parse_tasks(id)',
                    'pcap_filename': 'VARCHAR(200)',
                    'pcap_file_path': 'VARCHAR(500)',
                    'name': 'VARCHAR(200)',
                    'source_type': "VARCHAR(30) DEFAULT 'standalone'",
                    'status': "VARCHAR(20) DEFAULT 'pending'",
                    'progress': 'INTEGER DEFAULT 0',
                    'error_message': 'TEXT',
                    'touchdown_count': 'INTEGER DEFAULT 0',
                    'steady_count': 'INTEGER DEFAULT 0',
                    'created_at': 'DATETIME',
                    'completed_at': 'DATETIME',
                }
                for col_name, col_type in cols_to_add.items():
                    if col_name not in af_cols:
                        sync_conn.execute(
                            text(f"ALTER TABLE auto_flight_analysis_tasks ADD COLUMN {col_name} {col_type}")
                        )
                        print(f"[DB] 已添加 auto_flight_analysis_tasks.{col_name}")

            # 平台共享数据：试验架次 + 文件种类
            if 'shared_sorties' not in inspector.get_table_names():
                sync_conn.execute(text("""
                    CREATE TABLE shared_sorties (
                        id INTEGER PRIMARY KEY,
                        sortie_label VARCHAR(300) NOT NULL,
                        experiment_date DATE,
                        remarks TEXT,
                        uploaded_by_id INTEGER REFERENCES users(id),
                        created_at DATETIME
                    )
                """))
                sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shared_sorties_created ON shared_sorties(created_at)"))
                print("[DB] 已创建 shared_sorties 表")

            # 架次 × 构型 关联（幂等列迁移）
            if 'shared_sorties' in inspector.get_table_names():
                ss_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(shared_sorties)")).fetchall()}
                if 'aircraft_configuration_id' not in ss_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE shared_sorties ADD COLUMN aircraft_configuration_id INTEGER "
                        "REFERENCES aircraft_configurations(id)"
                    ))
                    sync_conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_shared_sorties_aircraft_cfg "
                        "ON shared_sorties(aircraft_configuration_id)"
                    ))
                    print("[DB] 已添加 shared_sorties.aircraft_configuration_id 列")
                if 'software_configuration_id' not in ss_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE shared_sorties ADD COLUMN software_configuration_id INTEGER "
                        "REFERENCES software_configurations(id)"
                    ))
                    sync_conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_shared_sorties_software_cfg "
                        "ON shared_sorties(software_configuration_id)"
                    ))
                    print("[DB] 已添加 shared_sorties.software_configuration_id 列")

            if 'shared_tsn_files' in inspector.get_table_names():
                st_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(shared_tsn_files)")).fetchall()}
                if 'sortie_id' not in st_cols:
                    sync_conn.execute(
                        text("ALTER TABLE shared_tsn_files ADD COLUMN sortie_id INTEGER REFERENCES shared_sorties(id)")
                    )
                    sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shared_tsn_sortie ON shared_tsn_files(sortie_id)"))
                    print("[DB] 已添加 shared_tsn_files.sortie_id")
                if 'asset_type' not in st_cols:
                    sync_conn.execute(text("ALTER TABLE shared_tsn_files ADD COLUMN asset_type VARCHAR(64)"))
                    print("[DB] 已添加 shared_tsn_files.asset_type")
                if 'video_processing_status' not in st_cols:
                    sync_conn.execute(
                        text("ALTER TABLE shared_tsn_files ADD COLUMN video_processing_status VARCHAR(32)")
                    )
                    print("[DB] 已添加 shared_tsn_files.video_processing_status")
                if 'video_processing_progress' not in st_cols:
                    sync_conn.execute(
                        text(
                            "ALTER TABLE shared_tsn_files ADD COLUMN video_processing_progress INTEGER"
                        )
                    )
                    print("[DB] 已添加 shared_tsn_files.video_processing_progress")
                if 'video_processing_error' not in st_cols:
                    sync_conn.execute(
                        text("ALTER TABLE shared_tsn_files ADD COLUMN video_processing_error TEXT")
                    )
                    print("[DB] 已添加 shared_tsn_files.video_processing_error")

            # ── 角色合并迁移：dev_tsn 并入 network_team（TSN/网络团队） ──
            # 背景：原 dev_tsn（TSN 开发团队）与 network_team（网络团队）合为同一团队，
            # 审批链从 4 步压缩为 3 步（去掉独立的 dev_tsn 会签节点）。
            if 'users' in inspector.get_table_names():
                migrated_users = sync_conn.execute(
                    text("UPDATE users SET role='network_team' WHERE role='dev_tsn'")
                ).rowcount or 0
                if migrated_users > 0:
                    print(f"[DB] 角色迁移：{migrated_users} 个 dev_tsn 账号 → network_team")

            if 'change_request_approvals' in inspector.get_table_names():
                # 先把审批历史记录里的角色名规整为 network_team（保留审计）
                migrated_appr = sync_conn.execute(
                    text(
                        "UPDATE change_request_approvals SET role='network_team' "
                        "WHERE role='dev_tsn'"
                    )
                ).rowcount or 0
                if migrated_appr > 0:
                    print(f"[DB] 审批记录角色重命名：{migrated_appr} 行 dev_tsn → network_team")

                # 压缩进行中审批链：仅针对原 4 步（max step_index=3）的 pending CR，
                # 删除原 step_index=2（dev_tsn 会签位），把 step_index=3（admin）提前到 2。
                old_chain_rows = sync_conn.execute(
                    text(
                        "SELECT cr_id FROM change_request_approvals "
                        "WHERE cr_id IN ("
                        "  SELECT id FROM protocol_change_requests WHERE overall_status='pending'"
                        ") "
                        "GROUP BY cr_id HAVING MAX(step_index) = 3"
                    )
                ).fetchall()
                old_ids = [row[0] for row in old_chain_rows]
                if old_ids:
                    ids_csv = ",".join(str(int(i)) for i in old_ids)
                    sync_conn.execute(
                        text(
                            f"DELETE FROM change_request_approvals "
                            f"WHERE cr_id IN ({ids_csv}) AND step_index = 2"
                        )
                    )
                    sync_conn.execute(
                        text(
                            f"UPDATE change_request_approvals SET step_index = 2 "
                            f"WHERE cr_id IN ({ids_csv}) AND step_index = 3"
                        )
                    )
                    # 若 current_step 指向已移除的 dev_tsn（=2）或原 admin（=3），
                    # 都收敛到新链的 admin 步 (=2)；否则不变
                    sync_conn.execute(
                        text(
                            f"UPDATE protocol_change_requests SET current_step = 2 "
                            f"WHERE id IN ({ids_csv}) AND current_step >= 2"
                        )
                    )
                    print(
                        f"[DB] 审批链压缩：{len(old_ids)} 条进行中 CR 已压缩为 3 步链"
                    )

            # ── 审批链再压缩：TSN 3 步（network_team → device_team → admin）→ 2 步（network_team → admin） ──
            # 背景：设备团队会签位下线，TSN 网络配置审批仅保留 TSN 团队自审 + 管理员终审。
            #      只影响 TSN 网络配置类 (draft_kind='tsn_network') 且仍在 pending 的 CR；
            #      历史已完结（approved/rejected/published）的记录不动，保留审计原貌。
            if 'change_request_approvals' in inspector.get_table_names():
                two_step_targets = sync_conn.execute(
                    text(
                        "SELECT DISTINCT cr_id FROM change_request_approvals "
                        "WHERE cr_id IN ("
                        "  SELECT id FROM protocol_change_requests "
                        "  WHERE overall_status='pending' "
                        "    AND (draft_kind IS NULL OR draft_kind='tsn_network')"
                        ") "
                        "GROUP BY cr_id HAVING MAX(step_index)=2"
                    )
                ).fetchall()
                tsn_ids = [row[0] for row in two_step_targets]
                if tsn_ids:
                    ids_csv = ",".join(str(int(i)) for i in tsn_ids)
                    sync_conn.execute(text(
                        f"DELETE FROM change_request_approvals "
                        f"WHERE cr_id IN ({ids_csv}) AND step_index=1 AND role='device_team'"
                    ))
                    sync_conn.execute(text(
                        f"UPDATE change_request_approvals SET step_index=1 "
                        f"WHERE cr_id IN ({ids_csv}) AND step_index=2"
                    ))
                    # current_step 收敛：原指向 device_team(1) 或 admin(2) 统统改为新 admin(1)
                    sync_conn.execute(text(
                        f"UPDATE protocol_change_requests SET current_step=1 "
                        f"WHERE id IN ({ids_csv}) AND current_step>=1"
                    ))
                    print(f"[DB] TSN 审批链再压缩：{len(tsn_ids)} 条 pending CR 从 3 步合并为 2 步")

            # ── notify_teams 列：CR + ProtocolVersion 双表都加（提交时存 CR、发布时拷贝到 version） ──
            if 'protocol_change_requests' in inspector.get_table_names():
                cr_cols = {row[1] for row in sync_conn.execute(
                    text("PRAGMA table_info(protocol_change_requests)")
                ).fetchall()}
                if 'notify_teams' not in cr_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE protocol_change_requests ADD COLUMN notify_teams JSON"
                    ))
                    print("[DB] 已添加 protocol_change_requests.notify_teams")

            if 'protocol_versions' in inspector.get_table_names():
                pv_cols = {row[1] for row in sync_conn.execute(
                    text("PRAGMA table_info(protocol_versions)")
                ).fetchall()}
                if 'notify_teams' not in pv_cols:
                    sync_conn.execute(text(
                        "ALTER TABLE protocol_versions ADD COLUMN notify_teams JSON"
                    ))
                    print("[DB] 已添加 protocol_versions.notify_teams")

        await conn.run_sync(_check_and_add_columns)

    await _ensure_bundles_for_available_versions()


def _split_event_analysis_tables(sync_conn) -> None:
    """Phase 1b：把 event_analysis_tasks 拆成 fms_event_analysis_tasks + fcc_event_analysis_tasks。

    策略（只执行一次，以 event_analysis_tasks__legacy 作为哨兵）：
      1. 按 rule_template 把旧任务行分别复制到 fms_event_analysis_tasks / fcc_event_analysis_tasks；
      2. 同步复制明细表 event_check_results / event_timeline_events；
      3. 把旧的 3 张表重命名为 *__legacy 保留，方便回滚；
      4. 整体放在同一个 transaction（外层 engine.begin）里执行，失败自动回滚。

    注意：新表结构由 SQLAlchemy ``Base.metadata.create_all`` 保证已经存在。
    """
    from sqlalchemy import text

    # 旧表明细行 id 可能和新表冲突（独立 fms/fcc 自增），因此这里按原 id 保留，
    # 新表是空的（刚 create_all 出来，没人用过），不会冲突。
    # 确保新表确实存在并且是空的（双保险）
    fms_task_count = sync_conn.execute(text("SELECT COUNT(*) FROM fms_event_analysis_tasks")).scalar()
    fcc_task_count = sync_conn.execute(text("SELECT COUNT(*) FROM fcc_event_analysis_tasks")).scalar()
    if fms_task_count or fcc_task_count:
        print(
            f"[DB] Phase 1b 跳过：fms/fcc 新表非空（fms={fms_task_count}, fcc={fcc_task_count}），"
            "视为已迁移，仅将旧表标记为 __legacy"
        )
    else:
        # 1) 分流任务行（默认模板按飞管处理，rule_template 仅 fcc_v1 时归 FCC）
        print("[DB] Phase 1b 开始拆表 event_analysis_tasks → fms/fcc ...")
        sync_conn.execute(text(
            """
            INSERT INTO fms_event_analysis_tasks (
                id, parse_task_id, bundle_version_id, pcap_filename, pcap_file_path,
                name, rule_template, status, progress, error_message,
                total_checks, passed_checks, failed_checks, created_at, completed_at
            )
            SELECT
                id, parse_task_id, bundle_version_id, pcap_filename, pcap_file_path,
                name, rule_template, status,
                COALESCE(progress, 0), error_message,
                COALESCE(total_checks, 0), COALESCE(passed_checks, 0), COALESCE(failed_checks, 0),
                created_at, completed_at
            FROM event_analysis_tasks
            WHERE COALESCE(rule_template, '') != 'fcc_v1'
            """
        ))
        sync_conn.execute(text(
            """
            INSERT INTO fcc_event_analysis_tasks (
                id, parse_task_id, bundle_version_id, pcap_filename, pcap_file_path,
                name, rule_template, status, progress, error_message,
                total_checks, passed_checks, failed_checks, created_at, completed_at
            )
            SELECT
                id, parse_task_id, bundle_version_id, pcap_filename, pcap_file_path,
                name, rule_template, status,
                COALESCE(progress, 0), error_message,
                COALESCE(total_checks, 0), COALESCE(passed_checks, 0), COALESCE(failed_checks, 0),
                created_at, completed_at
            FROM event_analysis_tasks
            WHERE COALESCE(rule_template, '') = 'fcc_v1'
            """
        ))

        # 2) 分流明细：event_check_results / event_timeline_events
        #    注意：原表列 `analysis_task_id` 指向 event_analysis_tasks.id，我们拆分后
        #    仍然用同一个 id 空间，所以直接按 task 归属分流即可。
        sync_conn.execute(text(
            """
            INSERT INTO fms_event_check_results
            SELECT r.* FROM event_check_results r
            JOIN event_analysis_tasks t ON t.id = r.analysis_task_id
            WHERE COALESCE(t.rule_template, '') != 'fcc_v1'
            """
        ))
        sync_conn.execute(text(
            """
            INSERT INTO fcc_event_check_results
            SELECT r.* FROM event_check_results r
            JOIN event_analysis_tasks t ON t.id = r.analysis_task_id
            WHERE COALESCE(t.rule_template, '') = 'fcc_v1'
            """
        ))
        sync_conn.execute(text(
            """
            INSERT INTO fms_event_timeline_events
            SELECT e.* FROM event_timeline_events e
            JOIN event_analysis_tasks t ON t.id = e.analysis_task_id
            WHERE COALESCE(t.rule_template, '') != 'fcc_v1'
            """
        ))
        sync_conn.execute(text(
            """
            INSERT INTO fcc_event_timeline_events
            SELECT e.* FROM event_timeline_events e
            JOIN event_analysis_tasks t ON t.id = e.analysis_task_id
            WHERE COALESCE(t.rule_template, '') = 'fcc_v1'
            """
        ))

        fms_after = sync_conn.execute(text("SELECT COUNT(*) FROM fms_event_analysis_tasks")).scalar()
        fcc_after = sync_conn.execute(text("SELECT COUNT(*) FROM fcc_event_analysis_tasks")).scalar()
        print(f"[DB] Phase 1b 迁移完成：fms={fms_after} 条，fcc={fcc_after} 条")

    # 3) 旧表重命名为 __legacy（保留回滚手段）
    sync_conn.execute(text("ALTER TABLE event_analysis_tasks RENAME TO event_analysis_tasks__legacy"))
    # 旧的明细表也一起归档
    legacy_tables = {"event_check_results", "event_timeline_events"}
    for tbl in legacy_tables:
        # 如果同名表存在则改名
        exists = sync_conn.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"
            ),
            {"n": tbl},
        ).scalar()
        if exists:
            sync_conn.execute(text(f"ALTER TABLE {tbl} RENAME TO {tbl}__legacy"))
    print("[DB] Phase 1b 旧表已改名为 *__legacy，保留备份")


async def _ensure_bundles_for_available_versions() -> None:
    """启动时对所有 Available 版本确保存在 bundle.json，缺失的自动补生成。

    幂等：已有的 bundle.json 不会被覆盖。对 PendingCode / Deprecated 版本不做处理。
    """
    try:
        from sqlalchemy import select as _select
        from .models import ProtocolVersion, AVAILABILITY_AVAILABLE  # lazy import
        from .services.bundle import generator as _bundle_gen
        from .services.bundle.generator import bundle_exists
    except Exception as exc:
        print(f"[Bundle] 启动检查跳过（导入失败）: {exc}")
        return

    try:
        async with async_session() as db:
            res = await db.execute(
                _select(ProtocolVersion).where(
                    ProtocolVersion.availability_status == AVAILABILITY_AVAILABLE
                )
            )
            versions = list(res.scalars().all())
            missing: list[int] = [v.id for v in versions if not bundle_exists(v.id)]
            if not missing:
                return
            print(f"[Bundle] 启动一致性检查：为 {len(missing)} 个 Available 版本补生成 bundle.json -> {missing}")
            for vid in missing:
                try:
                    await _bundle_gen.generate_bundle(db, vid)
                    print(f"[Bundle]   v{vid}: 已生成")
                except Exception as e:
                    print(f"[Bundle]   v{vid}: 生成失败 {type(e).__name__}: {e}")
    except Exception as exc:
        print(f"[Bundle] 启动检查失败: {exc}")