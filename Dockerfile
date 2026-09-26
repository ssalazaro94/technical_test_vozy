# syntax=docker/dockerfile:1

# --- Build: resolve and install dependencies with uv into /app/.venv ---------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer is reused while only the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the project itself, installed as a regular (non-editable) package.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- Runtime: only the virtual environment, as a non-root user ---------------
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8000

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

# Render injects PORT. Proxy headers: TLS terminates at Render's load balancer.
CMD ["sh", "-c", "exec uvicorn callaudit.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
