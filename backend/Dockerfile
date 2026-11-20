# Backend image shared by the `api`, `worker` and `migrate` services (decision 0008).
FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM python:3.15.2-slim-trixie AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.15.2-slim-trixie AS runtime
RUN useradd --system --uid 10001 --home-dir /app smartbasket && mkdir -p /data && chown smartbasket /data
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
USER smartbasket
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]
CMD ["smart-basket-api"]

# Worker image adds Playwright + Chromium + Xvfb so chains requiring a real headed browser
# (e.g. Dia, ADR 0006/0024) run 100% inside Docker without bloating `api` or `migrate`.
FROM runtime AS worker
USER root
COPY --from=uv /uv /usr/local/bin/uv
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update \
  && apt-get install -y --no-install-recommends xvfb libatomic1 \
  && uv pip install --python /app/.venv/bin/python --no-cache playwright \
  && /app/.venv/bin/playwright install --with-deps chromium \
  && rm -rf /var/lib/apt/lists/* \
  && chown -R smartbasket:smartbasket /ms-playwright
USER smartbasket
CMD ["xvfb-run", "-a", "smart-basket-worker"]
