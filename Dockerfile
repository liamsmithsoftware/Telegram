FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tehran \
    TELEGRAM_COLLECTOR_DATA_DIR=/app/data

WORKDIR /app

# tzdata is required for correct Asia/Tehran conversions inside the container
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY run.py ./
COPY tests ./tests
COPY pytest.ini ./

RUN mkdir -p /app/data/exports

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
