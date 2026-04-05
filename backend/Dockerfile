FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/uploads/pcap /app/uploads/protocols /app/data/results /app/data/exports

EXPOSE 8081

# SQLite 不宜多进程并发写；单 worker 也避免启动时多进程竞态执行 init_users
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
