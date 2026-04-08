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

