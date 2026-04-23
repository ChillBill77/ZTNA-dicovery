FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY correlator/pyproject.toml ./
COPY correlator/src ./src
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "correlator.main"]
