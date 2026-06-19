"""add user_id to activity_event

Revision ID: cbc237243efc
Revises: 49da717801f5
Create Date: 2026-06-19 13:53:15.362693

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'cbc237243efc'
down_revision: Union[str, Sequence[str], None] = '49da717801f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('activity_event', sa.Column('user_id', sa.String(), nullable=True), schema='rhizome')
    op.create_index('ix_activity_event_user_id', 'activity_event', ['user_id'], unique=False, schema='rhizome')
    # Backfill existing events to the single bootstrapped user.
    op.execute("UPDATE rhizome.activity_event SET user_id = '1' WHERE user_id IS NULL")


def downgrade() -> None:
    op.drop_index('ix_activity_event_user_id', table_name='activity_event', schema='rhizome')
    op.drop_column('activity_event', 'user_id', schema='rhizome')
