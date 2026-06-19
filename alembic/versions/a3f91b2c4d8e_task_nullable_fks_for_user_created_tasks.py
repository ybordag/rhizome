"""task nullable fks for user-created tasks

Revision ID: a3f91b2c4d8e
Revises: cbc237243efc
Create Date: 2026-06-19 15:00:00.000000

Make revision_id and generation_run_id nullable on Task so that tasks created
directly by the user (not via agent planning) don't need to reference a
planning revision or generation run.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'a3f91b2c4d8e'
down_revision: Union[str, Sequence[str], None] = 'cbc237243efc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('task', 'revision_id', nullable=True, schema='rhizome')
    op.alter_column('task', 'generation_run_id', nullable=True, schema='rhizome')


def downgrade() -> None:
    op.alter_column('task', 'generation_run_id', nullable=False, schema='rhizome')
    op.alter_column('task', 'revision_id', nullable=False, schema='rhizome')
