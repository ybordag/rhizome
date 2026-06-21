"""add user_id to interaction_record

Revision ID: a1b2c3d4e5f6
Revises: f7c4a1e9d2b5
Create Date: 2026-06-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7c4a1e9d2b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interaction_record', sa.Column('user_id', sa.String(), nullable=True), schema='rhizome')
    op.create_index('ix_interaction_record_user_id', 'interaction_record', ['user_id'], unique=False, schema='rhizome')
    # Backfill from the owning project where one exists; most rows (confirmations,
    # triage reviews) have no project_id and fall back to the single bootstrapped
    # user, matching the activity_event backfill (cbc237243efc).
    op.execute(
        """
        UPDATE rhizome.interaction_record AS ir
        SET user_id = gp.user_id
        FROM rhizome.gardening_project AS gp
        WHERE ir.project_id = gp.id AND ir.user_id IS NULL
        """
    )
    op.execute("UPDATE rhizome.interaction_record SET user_id = '1' WHERE user_id IS NULL")


def downgrade() -> None:
    op.drop_index('ix_interaction_record_user_id', table_name='interaction_record', schema='rhizome')
    op.drop_column('interaction_record', 'user_id', schema='rhizome')
