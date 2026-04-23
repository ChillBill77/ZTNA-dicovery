"""init flows hypertable + continuous aggregate

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    op.execute(
        """
        CREATE TABLE flows (
          time        TIMESTAMPTZ NOT NULL,
          src_ip      INET        NOT NULL,
          dst_ip      INET        NOT NULL,
          dst_port    INT         NOT NULL,
          proto       SMALLINT    NOT NULL,
          bytes       BIGINT      NOT NULL,
          packets     BIGINT      NOT NULL,
          flow_count  INT         NOT NULL,
          source      TEXT        NOT NULL
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('flows', 'time', chunk_time_interval => INTERVAL '1 hour');"
    )
    op.execute("SELECT add_retention_policy('flows', INTERVAL '30 days');")
    op.execute("CREATE INDEX ON flows (src_ip, time DESC);")
    op.execute("CREATE INDEX ON flows (dst_ip, dst_port, time DESC);")
    op.execute(
        "COMMENT ON COLUMN flows.source IS "
        "'adapter name (e.g. palo_alto, fortigate) — NOT firewall hostname';"
    )
    op.execute(
        """
        CREATE MATERIALIZED VIEW flows_1m
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 minute', time) AS bucket,
               src_ip, dst_ip, dst_port, proto,
               sum(bytes)      AS bytes,
               sum(packets)    AS packets,
               sum(flow_count) AS flow_count
        FROM flows
        GROUP BY bucket, src_ip, dst_ip, dst_port, proto
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('flows_1m',
            start_offset      => INTERVAL '3 hours',
            end_offset        => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute');
        """
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS flows_1m CASCADE;")
    op.execute("DROP TABLE IF EXISTS flows CASCADE;")
