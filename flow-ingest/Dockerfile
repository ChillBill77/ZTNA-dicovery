FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening. flow-ingest binds
# :5514/udp + :5514/tcp inside the container — well above the 1024 privileged
# threshold — so dropping to uid 1001 is safe. Traefik forwards the external
# :514 entrypoints to this port internally.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

# Copy the shared common package first so the editable install resolves.
COPY common/ /app/common/
COPY flow-ingest/pyproject.toml /app/flow-ingest/pyproject.toml
COPY flow-ingest/src /app/flow-ingest/src
RUN pip install --no-cache-dir -e /app/common && pip install --no-cache-dir -e /app/flow-ingest

RUN chown -R ztna:ztna /app
USER ztna

WORKDIR /app/flow-ingest
EXPOSE 5514/udp 5514/tcp
CMD ["python", "-m", "flow_ingest.main"]
