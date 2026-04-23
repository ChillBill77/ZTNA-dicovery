"""init applications, saas, dns, port_defaults

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE applications (
          id            SERIAL       PRIMARY KEY,
          name          TEXT         NOT NULL,
          description   TEXT,
          owner         TEXT,
          dst_cidr      CIDR         NOT NULL,
          dst_port_min  INT,
          dst_port_max  INT,
          proto         SMALLINT,
          priority      INT          NOT NULL DEFAULT 100,
          source        TEXT         NOT NULL DEFAULT 'manual',
          created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
          updated_by    TEXT
        );
        """
    )
    op.execute("CREATE INDEX applications_cidr_idx ON applications USING gist (dst_cidr inet_ops);")
    op.execute("CREATE INDEX applications_priority_idx ON applications (priority DESC);")

    op.execute(
        """
        CREATE TABLE application_audit (
          id              BIGSERIAL   PRIMARY KEY,
          application_id  INT         NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
          changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
          changed_by      TEXT        NOT NULL,
          op              TEXT        NOT NULL,
          before          JSONB,
          after           JSONB
        );
        """
    )

    op.execute(
        """
        CREATE TABLE saas_catalog (
          id             SERIAL PRIMARY KEY,
          name           TEXT   NOT NULL,
          vendor         TEXT,
          fqdn_pattern   TEXT   NOT NULL,
          category       TEXT,
          source         TEXT   NOT NULL DEFAULT 'manual',
          priority       INT    NOT NULL DEFAULT 100,
          UNIQUE (fqdn_pattern)
        );
        """
    )
    op.execute("CREATE INDEX saas_catalog_pattern_idx ON saas_catalog (fqdn_pattern);")

    op.execute(
        """
        CREATE TABLE dns_cache (
          dst_ip       INET        PRIMARY KEY,
          ptr          TEXT,
          resolved_at  TIMESTAMPTZ NOT NULL,
          ttl_seconds  INT         NOT NULL DEFAULT 3600,
          source       TEXT        NOT NULL
        );
        """
    )

    op.execute(
        """
        CREATE TABLE port_defaults (
          port   INT      NOT NULL,
          proto  SMALLINT NOT NULL,
          name   TEXT     NOT NULL,
          source TEXT     NOT NULL DEFAULT 'manual',   -- 'seeded' | 'manual'
          PRIMARY KEY (port, proto)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS port_defaults CASCADE;")
    op.execute("DROP TABLE IF EXISTS dns_cache CASCADE;")
    op.execute("DROP TABLE IF EXISTS saas_catalog CASCADE;")
    op.execute("DROP TABLE IF EXISTS application_audit CASCADE;")
    op.execute("DROP TABLE IF EXISTS applications CASCADE;")
