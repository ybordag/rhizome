"""task_series nullable fks for user-created series

Revision ID: b7c4e1f92a3d
Revises: a3f91b2c4d8e
Create Date: 2026-06-19 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b7c4e1f92a3d'
down_revision: Union[str, Sequence[str], None] = 'a3f91b2c4d8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('task_series', 'revision_id', nullable=True, schema='rhizome')
    op.alter_column('task_series', 'generation_run_id', nullable=True, schema='rhizome')


def downgrade() -> None:
    op.alter_column('task_series', 'generation_run_id', nullable=False, schema='rhizome')
    op.alter_column('task_series', 'revision_id', nullable=False, schema='rhizome')
