# 1. Use the official uv image as a builder
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Enable bytecode compilation and opt into copying executables
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Mount caches to speed up builds
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy application source code and install project
ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# 2. Final lightweight runtime image
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy installed virtual environment and source code from builder
COPY --from=builder /app /app

# Place virtual environment executables on PATH
ENV PATH="/app/.venv/bin:$PATH"

# Expose your application port (e.g., 8000)
EXPOSE 8000

# Set your start command (e.g., uvicorn, granian, or python main.py)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]