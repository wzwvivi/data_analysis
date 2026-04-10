FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads/pcap /app/uploads/protocols /app/data/results /app/data/exports

EXPOSE 8081

# 4 核默认：API workers=2；重任务通过独立进程池执行（TASK_PROCESS_WORKERS 默认 2）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "2"]
