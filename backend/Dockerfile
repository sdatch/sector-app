# Backend image — FastAPI + numpy/scipy compute layer.
# Same image runs locally (docker-compose) and on Railway; only env differs.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# System deps: build tools for scientific wheels (usually prebuilt, but safe).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source + migrations.
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# Artifacts volume mount point (memory-mapped snapshots).
RUN mkdir -p /srv/data/artifacts
ENV ARTIFACTS_DIR=/srv/data/artifacts

EXPOSE 8000

# Railway sets $PORT; default 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
