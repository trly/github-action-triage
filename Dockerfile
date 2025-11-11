# Build stage
FROM python:3.14-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY main.py ./

# Install dependencies
RUN uv sync --frozen

# Base runtime stage
FROM python:3.14-slim AS runtime-base

WORKDIR /app

# Create non-root user for running the application
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /bin/bash appuser

# Copy venv and application from builder
COPY --from=builder /build/.venv /app/venv
COPY --from=builder /build/main.py /app/
COPY --from=builder /build/src /app/src

# Set ownership of application files
RUN chown -R appuser:appuser /app

# Set base environment variables
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONPATH="/app/src:$PYTHONPATH" \
    PYTHONUNBUFFERED=1 \
    HOME=/app

# Web target (minimal, no claude)
FROM runtime-base AS web

USER appuser

EXPOSE 8000
CMD ["python", "main.py"]

# Worker target (with claude CLI)
FROM runtime-base AS worker

# Install git and curl for claude-code installation (as root before switching user)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Switch to non-root user
USER appuser

# Add ~/.local/bin to PATH for claude CLI
ENV PATH="/app/.local/bin:$PATH"

# Install claude-code CLI as appuser (installs to ~/.local/bin which is /app/.local/bin)
RUN curl -fsSL https://claude.ai/install.sh | bash

CMD ["python", "main.py"]