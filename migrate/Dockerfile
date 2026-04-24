FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Non-root runtime user (uid 1001) per P4 hardening. migrate is a one-shot
# runner that only speaks to Postgres; no sockets to bind.
RUN groupadd --system --gid 1001 ztna \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin ztna

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY seeds ./seeds

RUN chown -R ztna:ztna /app
USER ztna

CMD ["alembic", "upgrade", "head"]
