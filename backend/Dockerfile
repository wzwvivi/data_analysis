FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads/pcap /app/uploads/protocols /app/data/results /app/data/exports

EXPOSE 8081

# 2 核部署：API worker=1；重任务通过独立进程池执行（TASK_PROCESS_WORKERS=1）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
