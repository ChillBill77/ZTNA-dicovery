FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Copy the shared common package first so the editable install resolves.
COPY common/ /app/common/
COPY id-ingest/pyproject.toml /app/id-ingest/pyproject.toml
COPY id-ingest/src /app/id-ingest/src
RUN pip install --no-cache-dir -e /app/common && pip install --no-cache-dir -e /app/id-ingest
WORKDIR /app/id-ingest
# AD=516, ISE=517, ClearPass=518 (push-based syslog adapters bind these ports).
# Runs as root so it can bind the privileged <1024 ports directly. Siblings
# (api, flow-ingest, correlator, migrate) switched to uid 1001 non-root. To
# drop this container too, either (a) raise CAP_NET_BIND_SERVICE on the
# python interpreter via `setcap`, or (b) move the internal listener ports
# above 1024 and update `traefik/dynamic/tcp-udp.yml` service addresses
# accordingly.
EXPOSE 516/udp 516/tcp 517/udp 517/tcp 518/udp 518/tcp
CMD ["python", "-m", "id_ingest.main"]
