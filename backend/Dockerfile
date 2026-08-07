FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 libxslt1.1 curl && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
RUN uv pip install --system --no-cache --no-deps -e .

RUN useradd -u 10001 -m app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD curl -fsS localhost:8000/healthz || exit 1
ENTRYPOINT ["techtrend"]
CMD ["api", "--host", "0.0.0.0", "--port", "8000"]
