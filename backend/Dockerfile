FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

# Deps first, so code edits don't reinstall them
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY . .
EXPOSE 8000
# Tables are created on startup; no migrate step
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
