"""init identity events and user groups

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE identity_events (
          time         TIMESTAMPTZ NOT NULL,
          src_ip       INET        NOT NULL,
          user_upn     TEXT        NOT NULL,
          source       TEXT        NOT NULL,
          confidence   SMALLINT    NOT NULL,
          ttl_seconds  INT         NOT NULL,
          event_type   TEXT        NOT NULL,
          raw_id       TEXT
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('identity_events', 'time', chunk_time_interval => INTERVAL '1 hour');"
    )
    op.execute("SELECT add_retention_policy('identity_events', INTERVAL '30 days');")
    op.execute("CREATE INDEX ON identity_events (src_ip, time DESC);")
    op.execute("CREATE INDEX ON identity_events (user_upn, time DESC);")

    op.execute(
        """
        CREATE TABLE user_groups (
          user_upn     TEXT        NOT NULL,
          group_id     TEXT        NOT NULL,
          group_name   TEXT        NOT NULL,
          group_source TEXT        NOT NULL,
          refreshed_at TIMESTAMPTZ NOT NULL,
          PRIMARY KEY (user_upn, group_id)
        );
        """
    )
    op.execute("CREATE INDEX ON user_groups (group_id);")
    op.execute(
        """
        CREATE MATERIALIZED VIEW group_members AS
          SELECT group_id,
                 group_name,
                 array_agg(user_upn ORDER BY user_upn) AS members,
                 count(*) AS size
          FROM user_groups
          GROUP BY group_id, group_name;
        """
    )
    op.execute("CREATE INDEX ON group_members (group_id);")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS group_members CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_groups CASCADE;")
    op.execute("DROP TABLE IF EXISTS identity_events CASCADE;")
