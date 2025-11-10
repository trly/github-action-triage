# Build stage
FROM cgr.dev/chainguard/wolfi-base AS builder

WORKDIR /build

# Install Python and uv
RUN apk update && apk add --no-cache python-3.14 py3.14-pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY main.py ./

# Install dependencies
RUN uv sync --frozen

# Runtime stage
FROM cgr.dev/chainguard/wolfi-base

WORKDIR /app

# Install Python runtime
RUN apk update && apk add --no-cache python-3.14

# Copy venv and application from builder
COPY --from=builder /build/.venv /app/venv
COPY --from=builder /build/main.py /app/
COPY --from=builder /build/src /app/src

# Set environment variables
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONPATH="/app/src:$PYTHONPATH" \
    PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "main.py"]