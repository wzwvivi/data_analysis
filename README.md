# TSN日志数据分析平台

TSN数据包解析与分析平台，支持上传pcapng文件，按ICD协议定义解析，在线查看、分析、导出数据。

## 功能特性

- **协议库管理**：导入ICD Excel文件，自动解析端口和字段定义
- **数据解析**：上传pcapng文件，按协议定义解析TSN数据包
- **在线查看**：表格展示解析结果，支持分页、筛选
- **时序分析**：选择字段绘制时序曲线，支持多字段对比
- **数据导出**：支持CSV、Excel、Parquet格式导出

## 技术栈

### 后端
- Python 3.10+
- FastAPI
- SQLAlchemy (异步)
- SQLite
- pandas / pyarrow

### 前端
- React 18
- Ant Design 5
- ECharts
- Vite

## 快速开始

### Docker 一键启动（推荐）

```bash
docker compose up --build -d
```

服务默认地址：

- 前端：http://localhost:3000
- 后端：http://localhost:8081

数据目录（宿主机）：

- `backend-data/`（数据库、解析结果、导出）
- `backend-uploads/`（上传文件、协议文件）

容器停止后，以上目录数据仍可在宿主机直接访问。

### 1. 启动后端

```bash
cd backend

# 创建虚拟环境（可选）
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt

# 安装pcap解析库（二选一）
pip install scapy
# 或
pip install dpkt

# 启动服务
python run.py
```

后端服务运行在 http://localhost:8000

### 2. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端服务运行在 http://localhost:3000

## 使用流程

### 1. 导入协议配置

1. 进入「协议管理」页面
2. 点击「导入ICD文件」
3. 上传ICD Excel文件（如 `转换后的ICD6.0.1（260306）.xlsx`）
4. 填写协议名称和版本号
5. 点击导入

### 2. 上传解析数据

1. 进入「上传解析」页面
2. 上传pcapng文件
3. 选择协议版本
4. 可选择特定端口或解析全部
5. 点击「开始解析」

### 3. 查看结果

1. 解析完成后自动跳转到结果页
2. 按端口切换查看数据
3. 支持分页浏览

### 4. 数据分析

1. 点击「数据分析」进入分析页面
2. 选择端口和字段
3. 查看时序曲线
4. 支持缩放、拖拽查看

### 5. 导出数据

1. 在结果页点击导出按钮
2. 选择格式：CSV / Excel / Parquet
3. 下载文件

## 目录结构

```
tsn-log-analyzer/
├── backend/
│   ├── app/
│   │   ├── models/          # 数据模型
│   │   ├── routers/         # API路由
│   │   ├── services/        # 业务逻辑
│   │   ├── schemas/         # Pydantic模型
│   │   ├── config.py        # 配置
│   │   ├── database.py      # 数据库
│   │   └── main.py          # 主应用
│   ├── uploads/             # 上传文件
│   ├── data/                # 数据存储
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── src/
│   │   ├── components/      # 组件
│   │   ├── pages/           # 页面
│   │   ├── services/        # API服务
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## API文档

启动后端后访问 http://localhost:8000/docs 查看Swagger文档

## 注意事项

1. 解析大文件可能需要较长时间，请耐心等待
2. 建议使用Chrome或Edge浏览器
3. 导出大量数据时建议使用Parquet格式
4. 迁移到新服务器时，必须同时迁移 `backend-data/tsn_analyzer.db` 与 `backend-data/results/`，否则会出现“任务列表有记录但详情无结果”。
5. 详细迁移步骤见 `DEPLOY_MIGRATION.md`。
