FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening. correlator doesn't bind
# any privileged ports — it only makes outbound connections to Postgres and
# Redis and exposes :9100 for Prometheus scraping.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

# Install pinned third-party deps from the uv-generated lockfile first so this
# layer is cached unless requirements.txt changes (drift-checked in CI).
COPY correlator/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY correlator/pyproject.toml ./
COPY correlator/src ./src
# --no-deps: deps are already pinned + installed above; skip re-resolution.
RUN pip install --no-cache-dir --no-deps -e .

RUN chown -R ztna:ztna /app
USER ztna

EXPOSE 9100
CMD ["python", "-m", "correlator.main"]
