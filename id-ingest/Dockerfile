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
EXPOSE 516/udp 516/tcp 517/udp 517/tcp 518/udp 518/tcp
CMD ["python", "-m", "id_ingest.main"]
