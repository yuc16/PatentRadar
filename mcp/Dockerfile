FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATENTRADAR_MCP_HOST=0.0.0.0 \
    PATENTRADAR_MCP_PORT=8000 \
    PATENTRADAR_MCP_DATA_DIR=/app/data

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["uv", "run", "--frozen", "patentradar-mcp"]
