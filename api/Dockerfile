# Build context is the repo root (see docker-compose.yml: build.context=.).
# Multi-stage: first build the web SPA, then layer onto the python image.
FROM node:25-bookworm AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

# Install pinned third-party deps from the uv-generated lockfile first so this
# layer is cached unless requirements.txt changes (drift-checked in CI).
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/pyproject.toml ./
COPY api/src ./src
# --no-deps: deps are already pinned + installed above; skip re-resolution.
RUN pip install --no-cache-dir --no-deps .
COPY --from=web-build /web/dist /app/web-dist

RUN chown -R ztna:ztna /app
USER ztna

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
