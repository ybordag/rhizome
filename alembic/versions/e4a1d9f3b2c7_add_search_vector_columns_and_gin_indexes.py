"""add search_vector tsvector columns and GIN indexes

Revision ID: e4a1d9f3b2c7
Revises: d9e2f5a8b1c6
Create Date: 2026-06-19 00:00:00.000000

Adds a GENERATED ALWAYS AS STORED tsvector column and GIN index to each
searchable entity table. Used by GET /api/v1/search and the search_domain()
agent tool (Intelligence track Phase 2).

Postgres-only — Alembic never runs on SQLite (tests use init_db()).
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'e4a1d9f3b2c7'
down_revision: Union[str, Sequence[str], None] = 'd9e2f5a8b1c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "rhizome"


def _tsvector_expr(*cols: str) -> str:
    parts = " || ' ' || ".join(f"coalesce({c}, '')" for c in cols)
    return f"to_tsvector('english', {parts})"


_TABLES = [
    (
        "plant",
        _tsvector_expr("name", "variety", "notes", "special_instructions", "care_state_notes"),
    ),
    (
        "bed",
        _tsvector_expr("name", "location", "notes", "care_state_notes"),
    ),
    (
        "container",
        _tsvector_expr("name", "container_type", "location", "notes", "care_state_notes"),
    ),
    (
        "task",
        _tsvector_expr("title", "description", "notes"),
    ),
    (
        "gardening_project",
        _tsvector_expr("name", "notes"),
    ),
    (
        "incident_report",
        _tsvector_expr("incident_type", "summary", "notes"),
    ),
]


def upgrade() -> None:
    for table, expr in _TABLES:
        op.execute(
            f"ALTER TABLE {_SCHEMA}.{table} "
            f"ADD COLUMN search_vector tsvector "
            f"GENERATED ALWAYS AS ({expr}) STORED"
        )
        op.execute(
            f"CREATE INDEX ix_{table}_search_vector "
            f"ON {_SCHEMA}.{table} USING GIN(search_vector)"
        )


def downgrade() -> None:
    for table, _ in reversed(_TABLES):
        op.execute(
            f"DROP INDEX IF EXISTS {_SCHEMA}.ix_{table}_search_vector"
        )
        op.execute(
            f"ALTER TABLE {_SCHEMA}.{table} DROP COLUMN IF EXISTS search_vector"
        )
