FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

RUN mkdir -p /data/issues /data/docs

EXPOSE 8080

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    APP_CONFIG=/data/config.yaml \
    PYTHONPATH=/app

VOLUME ["/data"]

CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}"]
