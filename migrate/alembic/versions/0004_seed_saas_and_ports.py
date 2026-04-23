"""seed saas_catalog and port_defaults from CSV

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-22
"""

from __future__ import annotations

import csv
from pathlib import Path

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"


def _load_csv(name: str) -> list[dict[str, str]]:
    with (SEEDS_DIR / name).open(newline="") as fh:
        return list(csv.DictReader(fh))


def upgrade() -> None:
    conn = op.get_bind()

    for row in _load_csv("saas_catalog.csv"):
        conn.exec_driver_sql(
            """
            INSERT INTO saas_catalog (name, vendor, fqdn_pattern, category, source, priority)
            VALUES (%(name)s, %(vendor)s, %(fqdn_pattern)s, %(category)s, %(source)s, %(priority)s)
            ON CONFLICT (fqdn_pattern) DO NOTHING
            """,
            {**row, "priority": int(row["priority"])},
        )

    for row in _load_csv("port_defaults.csv"):
        conn.exec_driver_sql(
            """
            INSERT INTO port_defaults (port, proto, name, source)
            VALUES (%(port)s, %(proto)s, %(name)s, 'seeded')
            ON CONFLICT DO NOTHING
            """,
            {**row, "port": int(row["port"]), "proto": int(row["proto"])},
        )


def downgrade() -> None:
    op.execute("DELETE FROM saas_catalog WHERE source = 'seeded';")
    op.execute("DELETE FROM port_defaults WHERE source = 'seeded';")
