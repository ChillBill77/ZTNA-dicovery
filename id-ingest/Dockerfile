FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening. Internal listener ports
# are AD=5516, ISE=5517, ClearPass=5518 — all above the 1024 privileged
# threshold — so dropping to uid 1001 is safe. Traefik forwards the external
# :516/:517/:518 entrypoints to these ports internally.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

# Copy the shared common package first so the editable install resolves.
COPY common/ /app/common/
COPY id-ingest/pyproject.toml /app/id-ingest/pyproject.toml
COPY id-ingest/src /app/id-ingest/src
RUN pip install --no-cache-dir -e /app/common && pip install --no-cache-dir -e /app/id-ingest

RUN chown -R ztna:ztna /app
USER ztna

WORKDIR /app/id-ingest
EXPOSE 5516/udp 5516/tcp 5517/udp 5517/tcp 5518/udp 5518/tcp
CMD ["python", "-m", "id_ingest.main"]
