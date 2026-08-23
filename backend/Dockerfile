FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/app/.ms-playwright

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# SCS-6: Playwright headless Chromium for Strava auto-login. Run AFTER
# the venv exists so `playwright install` finds the package. --with-deps
# pulls the apt libs Chromium needs (libnss, libatk, etc.) ~250MB total.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    .venv/bin/playwright install --with-deps chromium

# Headless Claude Code CLI for the `claude_cli` provider — calls run on
# the machine's Claude subscription instead of per-token API billing.
# Node comes from Debian (18.x, which the CLI supports). Both are only
# used when the provider is selected; an install that never enables it
# pays ~150 MB of image and nothing else.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

# Bake build provenance so /version can report it.
ARG GIT_SHA=unknown
ARG BUILD_TIME=unknown
ENV GIT_SHA=${GIT_SHA} \
    BUILD_TIME=${BUILD_TIME}

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && fastapi run src/myvitals/main.py --host 0.0.0.0 --port 8000"]
