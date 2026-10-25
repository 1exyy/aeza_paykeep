# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CONTRACT_PATH=/docs/api/openapi.yaml \
    ATTACHMENTS_DIR=/data/attachments

RUN pip install --no-cache-dir uv==0.11.23

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY docs/api /docs/api
RUN uv sync --frozen --no-dev \
    && useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /data/attachments \
    && chown -R app:app /data/attachments

USER app
EXPOSE 8000
# Migrations, then demo data when SEED_DEMO_DATA=true (idempotent), then the API.
CMD ["sh", "-c", "alembic upgrade head && if [ \"$SEED_DEMO_DATA\" = true ]; then python -m app.seed; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
