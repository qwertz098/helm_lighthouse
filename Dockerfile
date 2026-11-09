# ── Build stage: compiles any wheel that has no prebuilt binary for the platform ──
FROM python:3.12-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Runtime stage: no compiler, no pip ──
FROM python:3.12-slim

WORKDIR /app

# Bind-mount the wheels instead of copying them, so they add no image layer
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-cache-dir --no-index /wheels/*.whl \
    && pip uninstall -y pip

COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/

RUN mkdir -p /data/issues /data/docs

EXPOSE 8080

# MALLOC_ARENA_MAX: glibc otherwise keeps a malloc arena per thread, which costs
# RAM on small devices for no gain in this mostly single-threaded app
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    APP_CONFIG=/data/config.yaml \
    PYTHONPATH=/app \
    MALLOC_ARENA_MAX=2

VOLUME ["/data"]

# Release shown on the settings page; the workflow and the edge build scripts pass git describe
ARG APP_RELEASE=dev
ENV APP_RELEASE=${APP_RELEASE}

CMD ["sh", "-c", "exec uvicorn app.main:app --host ${APP_HOST} --port ${APP_PORT}"]
