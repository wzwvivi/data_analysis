# -*- coding: utf-8 -*-
"""数据库配置"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from .config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)
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

            # protocol_versions 表迁移：版本生命周期状态
            if 'protocol_versions' in inspector.get_table_names():
                pv_cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(protocol_versions)")).fetchall()}
                pv_add = {
                    'availability_status': "VARCHAR(20) NOT NULL DEFAULT 'Available'",
                    'activated_at': 'DATETIME',
                    'activated_by': 'VARCHAR(64)',
                    'forced_activation': 'BOOLEAN NOT NULL DEFAULT 0',
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
                cr_cols = {
                    row[1]
                    for row in sync_conn.execute(
                        text("PRAGMA table_info(protocol_change_requests)")
                    ).fetchall()
                }
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

        await conn.run_sync(_check_and_add_columns)