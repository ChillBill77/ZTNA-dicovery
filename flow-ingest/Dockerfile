FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Copy the shared common package first so the editable install resolves.
COPY common/ /app/common/
COPY flow-ingest/pyproject.toml /app/flow-ingest/pyproject.toml
COPY flow-ingest/src /app/flow-ingest/src
RUN pip install --no-cache-dir -e /app/common && pip install --no-cache-dir -e /app/flow-ingest
WORKDIR /app/flow-ingest
EXPOSE 5514/udp 5514/tcp
CMD ["python", "-m", "flow_ingest.main"]
