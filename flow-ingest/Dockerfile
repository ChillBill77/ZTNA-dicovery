FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening. flow-ingest binds
# :5514/udp + :5514/tcp inside the container — well above the 1024 privileged
# threshold — so dropping to uid 1001 is safe. Traefik forwards the external
# :514 entrypoints to this port internally.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

# Install pinned third-party deps from the uv-generated lockfile first so this
# layer is cached unless requirements.txt changes (drift-checked in CI). The
# lockfile also lists `-e ../common`; we strip it here because common is a
# local package (no external deps beyond what's already pinned in the lockfile)
# and we install it editably below.
COPY flow-ingest/requirements.txt /app/flow-ingest/requirements.txt
RUN grep -v '^-e ' /app/flow-ingest/requirements.txt > /tmp/flow-ingest-thirdparty.txt \
    && pip install --no-cache-dir -r /tmp/flow-ingest-thirdparty.txt \
    && rm /tmp/flow-ingest-thirdparty.txt
# Now bring in the local packages (common + service) and install them with
# --no-deps so they don't re-resolve any third-party requirements.
COPY common/ /app/common/
COPY flow-ingest/pyproject.toml /app/flow-ingest/pyproject.toml
COPY flow-ingest/src /app/flow-ingest/src
RUN pip install --no-cache-dir --no-deps -e /app/common \
    && pip install --no-cache-dir --no-deps -e /app/flow-ingest

RUN chown -R ztna:ztna /app
USER ztna

WORKDIR /app/flow-ingest
EXPOSE 5514/udp 5514/tcp
CMD ["python", "-m", "flow_ingest.main"]
