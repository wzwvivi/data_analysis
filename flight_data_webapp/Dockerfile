FROM python:3.11-slim

WORKDIR /app

# 不在此镜像内做 apt install，故不再强制换 Debian 源；阿里云源偶发 502 会导致整镜构建失败。
# 如需国内加速，可在构建机配置 Docker registry mirror 或使用 buildkit 网络代理。

# 使用默认 PyPI，避免国内镜像偶发超时/502；拉长超时与重试以提高构建成功率
ENV PIP_DEFAULT_TIMEOUT=300
COPY requirements.txt .
RUN pip install --retries 15 --no-cache-dir -r requirements.txt gunicorn

COPY app.py .
COPY templates/ templates/
COPY static/ static/
COPY entrypoint.sh /entrypoint.sh

RUN mkdir -p data uploads /runtime/data /runtime/uploads/flight_assistant \
    && chmod +x /entrypoint.sh \
    && sed -i 's/\r$//' /entrypoint.sh

ENV FLIGHT_DATA_DB_PATH=/runtime/data/tsn_analyzer.db \
    FLIGHT_DATA_UPLOAD_DIR=/runtime/uploads/flight_assistant \
    FLIGHT_DATA_WAIT_SECS=60

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "600", "app:app"]
