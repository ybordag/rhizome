"""add thread session_context column

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-21 00:00:00.000000

Structured startup/session context for Verdant's SessionStrip (#146).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "rhizome"


def upgrade() -> None:
    op.add_column(
        "thread",
        sa.Column("session_context", sa.JSON(), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("thread", "session_context", schema=_SCHEMA)
