# syntax=docker/dockerfile:1.7
# Imagem única dos mocks; o compose escolhe o app no comando:
#   uvicorn mocks_equipes.<identidade|pedidos|logistica>:app --host 0.0.0.0 --port <porta>

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package mocks-equipes

FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER app
CMD ["uvicorn", "mocks_equipes.pedidos:app", "--host", "0.0.0.0", "--port", "8008"]
