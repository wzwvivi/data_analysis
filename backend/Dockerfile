FROM python:3.12-slim

WORKDIR /app

# Debian 官方源偶发 502；多轮重试以提高 CI / 本地构建成功率
RUN set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    for i in 1 2 3 4 5; do \
      apt-get update -o Acquire::http::Timeout=120 -o Acquire::Retries=5 \
      && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/* \
      && break; \
      echo "apt failed (attempt $i), retrying in 20s..."; \
      sleep 20; \
    done; \
    command -v ffmpeg >/dev/null

COPY requirements.txt .
ENV PIP_DEFAULT_TIMEOUT=300
RUN pip install --retries 15 --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads/pcap /app/uploads/protocols /app/data/results /app/data/exports

EXPOSE 8081

# API worker 固定 1：重任务由 app/task_executor.py 的 ProcessPoolExecutor
# 独立子进程承担，不会阻塞 asyncio event loop。
# 若开多个 uvicorn worker，每个 worker 会各自建一份 ProcessPool，
# 实际解析并发 = uvicorn_workers × TASK_PROCESS_WORKERS，会超出内存预算。
# 因此这里保持 --workers 1，由 compose 的 TASK_PROCESS_WORKERS 严格控制并发。
# --loop uvloop 在 uvicorn[standard] 中默认启用，显式写出便于检查。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--loop", "uvloop"]
