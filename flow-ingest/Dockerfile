FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY flow-ingest/pyproject.toml ./
COPY flow-ingest/src ./src
RUN pip install --no-cache-dir -e .
EXPOSE 5514/udp 5514/tcp
CMD ["python", "-m", "flow_ingest.main"]
