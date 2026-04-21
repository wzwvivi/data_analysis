FROM python:3.11-slim

WORKDIR /app

# Switch apt to Aliyun mirror
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update -qq

# Switch pip to Aliyun mirror
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

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
