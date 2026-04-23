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
COPY api/pyproject.toml ./
COPY api/src ./src
RUN pip install --no-cache-dir .
COPY --from=web-build /web/dist /app/web-dist
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
