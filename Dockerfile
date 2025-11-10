# Build stage
FROM python:3.13-slim AS builder

WORKDIR /build

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy source code
COPY src ./src
COPY main.py ./

# Build the package
RUN uv build

# Runtime stage
FROM cgr.dev/chainguard/python:latest

WORKDIR /app

# Copy built package and dependencies from builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/main.py /app/
COPY --from=builder /build/src /app/src

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py"]
