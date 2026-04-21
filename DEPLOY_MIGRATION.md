# 部署与迁移规范（含数据库与结果文件）

本文用于统一团队的部署/迁移流程，避免出现“任务列表存在，但点开无结果”问题。

## 1. 当前数据挂载方式

`docker-compose.yml` 使用宿主机 bind mount：

- `./backend-data:/app/data`
- `./backend-uploads:/app/uploads`

因此容器停止后，数据仍保留在宿主机 `backend-data` 与 `backend-uploads` 目录。

## 2. 必带数据与可选数据

### 必带（缺一不可）

- `backend-data/tsn_analyzer.db`（任务、解析器、配置等元数据）
- `backend-data/results/`（任务明细 Parquet 文件）

> 仅迁移 `tsn_analyzer.db` 不够。若缺少 `results`，会出现“任务存在但无结果”。

### 建议带

- `backend-uploads/protocols/`（协议 Excel 文件）

### 可不带（可清理）

- `backend-data/exports/`（导出文件）
- 临时测试上传目录（如 `backend-uploads/compare/`、`backend-uploads/standalone_events/`）

## 3. 旧服务器备份

在项目根目录执行：

```bash
docker compose down

tar -czf tsn_migration_bundle.tar.gz \
  backend-data/tsn_analyzer.db \
  backend-data/results \
  backend-uploads/protocols
```

若 `backend-uploads/protocols` 不存在，可去掉该路径。

## 4. 新服务器恢复

```bash
# 1) 拉代码
git clone https://github.com/wzwvivi/data_analysis2.git
cd data_analysis2

# 2) 解压迁移包到项目根目录
tar -xzf /path/to/tsn_migration_bundle.tar.gz -C .

# 3) 启动
docker compose up --build -d
```

## 5. 恢复后检查（必须执行）

```bash
# 必须存在
ls -lah backend-data/tsn_analyzer.db
ls -lah backend-data/results

# 至少应有一批 parquet
find backend-data/results -name "*.parquet" | head
```

若任务列表有记录但详情无结果，优先检查 `backend-data/results/<task_id>/` 是否存在对应 `port_*.parquet`。

## 6. 常见问题

### Q1: 为什么任务列表有，但点进去是空？

A: DB 中有任务索引，但 `backend-data/results` 缺失或不完整。

### Q2: Docker 停止后数据还在吗？

A: 在当前 bind mount 模式下还在，数据直接位于宿主机目录。

## 7. 版本库建议

不建议长期把大体积 Parquet 全量提交到 Git。推荐：

- 代码走 Git
- 迁移数据走离线包（本规范中的 `tsn_migration_bundle.tar.gz`）或对象存储

## 8. 飞行助手分析 (flight_data_webapp) 迁移补充

集成后，`flight-assistant` 服务与 TSN 后端共用同一个 SQLite 文件，迁移时要一起带。

### 8.1 服务拓扑与端口

| 服务 | 默认端口 | 镜像构建路径 | 说明 |
| --- | --- | --- | --- |
| backend | 8081 | `./backend` | TSN FastAPI 主服务 |
| frontend | 3000 | `./frontend` | React 前端 |
| flight-assistant | 8082 | `./flight_data_webapp` | 独立 Flask，新标签页打开 |

### 8.2 必带数据（在第 2 节基础上追加）

- `backend-runtime/data/tsn_analyzer.db`（TSN 与飞行助手**共用**的同一份 DB）
- `backend-runtime/uploads/flight_assistant/`（飞行助手上传的 CSV 原始文件和合并结果；缺失会导致历史 dataset 无法重新下载/再分析）

### 8.3 备份命令（含飞行助手）

```bash
docker compose down

tar -czf tsn_migration_bundle.tar.gz \
  backend-runtime/data/tsn_analyzer.db \
  backend-runtime/data/results \
  backend-runtime/uploads/protocols \
  backend-runtime/uploads/flight_assistant
```

### 8.4 启用菜单入口（新机器）

只影响 TSN 前端是否展示"飞行助手分析"入口，对飞行助手本身不影响：

```yaml
# docker-compose.yml > services.backend.environment 追加
- FLIGHT_ASSISTANT_URL=http://<新机器内网或反代域名>:8082
```

然后 `docker compose up --build -d`。

### 8.5 数据一致性与并发

- 飞行助手 `get_db()` 会 `PRAGMA journal_mode=WAL`，两端并发读写同一份 `.db` 安全。
- compose 里 `flight-assistant` 通过 `depends_on: backend` 等待后端容器启动；
  另外容器内 `entrypoint.sh` 会再等待 `FLIGHT_DATA_DB_PATH` 对应的 `.db` 文件
  最多 60 秒，避免首启抢先建库导致字段缺失。超时后仍会正常启动（SQLite 表
  按名隔离，两端各自 `CREATE TABLE IF NOT EXISTS`）。

### 8.6 安全提示（务必阅读）

- `flight_data_webapp` 没有鉴权，不要把 8082 直接暴露在公网。
- 生产环境建议把 `flight-assistant.ports` 改为 `"127.0.0.1:8082:5000"`，
  或通过 nginx/Traefik + basic auth / OAuth2-Proxy 反向代理。
- TSN 前端菜单的"管理员可见"只是软隐藏，不能阻止直连 8082 的请求。

