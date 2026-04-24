# 部署与迁移规范（含数据库与结果文件）

本文用于统一团队的部署/迁移流程，避免出现“任务列表存在，但点开无结果”问题。

## 1. 当前数据挂载方式

`docker-compose.yml` 使用单一宿主机 bind mount：

- `./backend-runtime:/app_runtime`（TSN backend，`APP_BASE_DIR=/app_runtime`）
- `./backend-runtime:/runtime`（flight-assistant，与 backend 共享同一份宿主机目录）

容器内的数据按子目录组织，关键路径是：

| 用途 | 容器内路径 | 宿主机路径 |
| --- | --- | --- |
| SQLite 元数据 DB（TSN + 飞行助手共用） | `/app_runtime/data/tsn_analyzer.db` | `./backend-runtime/data/tsn_analyzer.db` |
| 解析结果 Parquet | `/app_runtime/data/results/<task_id>/` | `./backend-runtime/data/results/<task_id>/` |
| 导出文件（可清理） | `/app_runtime/data/exports/` | `./backend-runtime/data/exports/` |
| PCAP 原始上传 | `/app_runtime/uploads/pcaps/` | `./backend-runtime/uploads/pcaps/` |
| 平台共享 TSN 文件 | `/app_runtime/uploads/shared_tsn/` | `./backend-runtime/uploads/shared_tsn/` |
| 协议 Excel | `/app_runtime/uploads/protocols/` | `./backend-runtime/uploads/protocols/` |
| 飞行助手 CSV | `/app_runtime/uploads/flight_assistant/` | `./backend-runtime/uploads/flight_assistant/` |

> 注：历史文档曾出现 `backend-data` / `backend-uploads` 两个独立目录，当前已统一收敛到 `backend-runtime`，迁移时**只关心一个目录**即可。

容器停止后，数据仍保留在宿主机 `./backend-runtime` 下。

## 2. 必带数据与可选数据

### 必带（缺一不可）

- `backend-runtime/data/tsn_analyzer.db` — 任务、解析器、配置、用户、飞行助手 dataset 等元数据；**TSN 与飞行助手共用同一份 DB**。
- `backend-runtime/data/results/` — 任务明细 Parquet 文件；默认永久保留（`RESULT_RETENTION_DAYS=0`），若开启自动清理请先评估策略。

> 仅迁移 `tsn_analyzer.db` 不够。若缺少 `results/`，会出现“任务存在但无结果”。

### 建议带

- `backend-runtime/uploads/protocols/` — 协议 Excel；新环境需要重新导入协议时无需；但带上可减少返工。
- `backend-runtime/uploads/flight_assistant/` — 飞行助手上传的 CSV/合并结果；缺失会导致历史 dataset 无法再下载或再分析。

### 保留策略（运行时可调）

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RESULT_RETENTION_DAYS` | `0` | 解析结果 Parquet 保留天数，`0` 表示永久保留，启动/上传时会按此值回收 `results/`。 |
| `SHARED_TSN_RETENTION_DAYS` | `20` | 管理员上传的平台共享 TSN 文件保留天数，超期启动/上传时清理 `uploads/shared_tsn/`。 |
| `MIN_FREE_DISK_MB` | `2048` | 剩余磁盘低于该值拒绝新上传；不涉及自动清理。 |

**迁移前一定要核实目标环境的上述变量**，否则可能出现“搬过去第二天结果就被清掉”的情况。

### 可不带（可清理）

- `backend-runtime/data/exports/` — 用户导出的临时文件。
- `backend-runtime/uploads/pcaps/` — 如果全部任务都已解析完毕且不再 rerun，可不带；否则建议一起带。
- 临时测试目录（如 `backend-runtime/uploads/compare/`、`backend-runtime/uploads/standalone_events/`）。

## 3. 旧服务器备份

在项目根目录执行：

```bash
docker compose down

tar -czf tsn_migration_bundle.tar.gz \
  backend-runtime/data/tsn_analyzer.db \
  backend-runtime/data/results \
  backend-runtime/uploads/protocols \
  backend-runtime/uploads/flight_assistant
```

如需减小包体积，可暂时不带 `uploads/protocols` 与 `uploads/flight_assistant`，但需要在新环境上重新导入协议或放弃历史飞行助手 dataset。

## 4. 新服务器恢复

```bash
# 1) 拉代码
git clone https://github.com/wzwvivi/data_analysis2.git
cd data_analysis2

# 2) 解压迁移包到项目根目录（会还原到 backend-runtime/）
tar -xzf /path/to/tsn_migration_bundle.tar.gz -C .

# 3) 按需准备 .env，至少覆盖以下两项
#    JWT_SECRET=<生产用的随机串>
#    FLIGHT_ASSISTANT_URL=http://<本机内网IP或反代域名>:8082

# 4) 启动
docker compose up --build -d
```

## 5. 恢复后检查（必须执行）

```bash
# 必须存在
ls -lah backend-runtime/data/tsn_analyzer.db
ls -lah backend-runtime/data/results

# 至少应有一批 parquet
find backend-runtime/data/results -name "*.parquet" | head
```

若任务列表有记录但详情无结果，优先检查 `backend-runtime/data/results/<task_id>/` 是否存在对应 `port_*.parquet`。

## 6. 常见问题

### Q1: 为什么任务列表有，但点进去是空？

A: DB 中有任务索引，但 `backend-runtime/data/results` 缺失或不完整；也可能是 `RESULT_RETENTION_DAYS` 被设为非 0 且目标任务已过期被清理。

### Q2: Docker 停止后数据还在吗？

A: 在当前 bind mount 模式下还在，数据直接位于宿主机 `./backend-runtime` 目录。

### Q3: 共享原始数据为什么不见了？

A: 管理员上传的共享 TSN 文件默认保留 20 天（`SHARED_TSN_RETENTION_DAYS`），到期会在下次启动/上传时被清理；元数据仍在 DB 中，只是无法重新下载。

## 7. 版本库建议

不建议长期把大体积 Parquet 全量提交到 Git。推荐：

- 代码走 Git
- 迁移数据走离线包（本规范中的 `tsn_migration_bundle.tar.gz`）或对象存储

## 8. 飞行助手分析 (flight_data_webapp) 说明

`flight-assistant` 服务与 TSN 后端共用同一个 `backend-runtime` 目录（也就是同一份 SQLite），迁移时不需要额外复制。

### 8.1 服务拓扑与端口

| 服务 | 默认端口 | 镜像构建路径 | 说明 |
| --- | --- | --- | --- |
| backend | 8081 | `./backend` | TSN FastAPI 主服务 |
| frontend | 3000 | `./frontend` | React 前端 |
| flight-assistant | 8082 | `./flight_data_webapp` | 独立 Flask，新标签页打开 |

### 8.2 启用菜单入口（新机器）

菜单入口仅受 `FLIGHT_ASSISTANT_URL` 的可达性影响，不影响 flight-assistant 本身运行：

```yaml
# docker-compose.yml > services.backend.environment 追加或在 .env 设置
- FLIGHT_ASSISTANT_URL=http://<新机器内网或反代域名>:8082
```

### 8.3 数据一致性与并发

- 飞行助手 `get_db()` 会 `PRAGMA journal_mode=WAL`，两端并发读写同一份 `.db` 是安全的。
- compose 里 `flight-assistant` 通过 `depends_on: backend` 等待后端容器启动；
  另外容器内 `entrypoint.sh` 会再等待 `FLIGHT_DATA_DB_PATH` 对应的 `.db` 文件
  最多 60 秒，避免首启抢先建库导致字段缺失。超时后仍会正常启动（SQLite 表
  按名隔离，两端各自 `CREATE TABLE IF NOT EXISTS`）。

### 8.4 安全提示（务必阅读）

- `flight_data_webapp` **没有鉴权**，不要把 8082 直接暴露在公网。
- 生产环境建议把 `flight-assistant.ports` 改为 `"127.0.0.1:8082:5000"`，
  或通过 nginx/Traefik + basic auth / OAuth2-Proxy 反向代理。
- TSN 前端菜单的"管理员可见"只是软隐藏，不能阻止直连 8082 的请求。
- 同理：`JWT_SECRET` 必须通过 `.env` 覆盖，切勿使用默认值进生产。
