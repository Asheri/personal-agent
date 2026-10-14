# Container image for the sci-rag server (Cloud Run friendly).
#
#   docker build -t sci-rag .
#   docker run -p 8080:8080 --env-file .env sci-rag
#
# The image contains the package, the domain profile, and the migrations
# (so `sci-rag db upgrade` can run from a job using this same image). It
# deliberately does NOT include the docling extra; PDF-heavy ingestion is
# better run where you can afford the larger image, or with the pypdf
# fallback.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY domain ./domain
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SCI_RAG_SERVER_HOST=0.0.0.0
EXPOSE 8080
# Cloud Run injects PORT; sci-rag serve honors it.
CMD ["sci-rag", "serve"]
