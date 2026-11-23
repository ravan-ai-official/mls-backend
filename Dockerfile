# Production image for mls-backend (Django + Gunicorn + WhiteNoise).
# Multi-stage keeps the final image small -> cheaper Artifact Registry storage
# and faster Cloud Run cold starts.

# ---------- Stage 1: build wheels ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# BuildKit cache mount keeps pip's HTTP cache across build attempts so
# a mid-stream broken-pipe only costs the one wheel, not the whole run.
# pip >= 24.3 is required for --resume-retries (resumes partial downloads
# on mid-stream connection drops, which the slim image's older pip lacks).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade "pip>=24.3" && \
    pip wheel --wheel-dir /wheels \
        --default-timeout=600 \
        --retries=10 \
        --resume-retries=10 \
        -r requirements.txt


# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=backend.settings \
    PORT=8080

WORKDIR /app

# Runtime libs only (no compiler) -> smaller image.
# libpq5 for psycopg2, libgl1/libglib2.0-0 for opencv-python at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY . .

# Collect static at build time so startup is fast.
# Dummy env vars so settings.py imports cleanly; real values come at runtime.
RUN DATABASE_URL="sqlite:///tmp.db" \
    SECRET_KEY="build-time-only" \
    DEBUG=False \
    python manage.py collectstatic --noinput

# Non-root user (Cloud Run requires $PORT, not a fixed user, but this is good hygiene).
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8080

# Cloud Run sends SIGTERM; gunicorn handles it. One worker + threads keeps
# memory low (fits in 512Mi Cloud Run instance). Tune WEB_CONCURRENCY/THREADS
# via env vars if you scale up.
CMD exec gunicorn backend.wsgi:application \
        --bind 0.0.0.0:${PORT} \
        --workers ${WEB_CONCURRENCY:-1} \
        --threads ${WEB_THREADS:-8} \
        --timeout ${WEB_TIMEOUT:-120} \
        --access-logfile - \
        --error-logfile -
