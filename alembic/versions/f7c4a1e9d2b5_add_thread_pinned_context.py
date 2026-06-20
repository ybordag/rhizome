"""add thread pinned_context column

Revision ID: f7c4a1e9d2b5
Revises: e4a1d9f3b2c7
Create Date: 2026-06-19 00:00:00.000000

JSON array of {subject_type, subject_id} dicts pinned to a thread for
persistent context injection at session start (issue #127).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f7c4a1e9d2b5'
down_revision: Union[str, Sequence[str], None] = 'e4a1d9f3b2c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "rhizome"


def upgrade() -> None:
    op.add_column(
        "thread",
        sa.Column("pinned_context", sa.JSON(), nullable=False, server_default="[]"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("thread", "pinned_context", schema=_SCHEMA)
