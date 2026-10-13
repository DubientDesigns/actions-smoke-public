# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    CIT_DB_DIR=/app/db
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/cit ./cit
COPY db /app/db
RUN uv sync --frozen --no-dev \
 && useradd --system --uid 10001 --home /app cit
USER cit
ENV PATH=/app/backend/.venv/bin:$PATH

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).status==200 else 1)" || exit 1

CMD ["cit", "api"]
