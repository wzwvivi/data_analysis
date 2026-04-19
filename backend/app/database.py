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

        await conn.run_sync(_check_and_add_columns)