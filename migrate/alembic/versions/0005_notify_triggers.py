"""add NOTIFY triggers for applications and saas_catalog

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, channel in (("applications", "applications_changed"),
                           ("saas_catalog", "saas_changed")):
        op.execute(f"""
            CREATE OR REPLACE FUNCTION _notify_{table}() RETURNS trigger AS $$
            BEGIN
              PERFORM pg_notify('{channel}', COALESCE(NEW.id::text, OLD.id::text, ''));
              RETURN COALESCE(NEW, OLD);
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER {table}_notify
              AFTER INSERT OR UPDATE OR DELETE ON {table}
              FOR EACH ROW EXECUTE FUNCTION _notify_{table}();
        """)


def downgrade() -> None:
    for table in ("applications", "saas_catalog"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_notify ON {table};")
        op.execute(f"DROP FUNCTION IF EXISTS _notify_{table}();")
