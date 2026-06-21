"""add user_id to incident_report

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-20 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('incident_report', sa.Column('user_id', sa.String(), nullable=True), schema='rhizome')
    op.create_index('ix_incident_report_user_id', 'incident_report', ['user_id'], unique=False, schema='rhizome')
    # Backfill from the owning project where one exists; fall back to the single
    # bootstrapped user, matching the interaction_record backfill (a1b2c3d4e5f6).
    op.execute(
        """
        UPDATE rhizome.incident_report AS ir
        SET user_id = gp.user_id
        FROM rhizome.gardening_project AS gp
        WHERE ir.project_id = gp.id AND ir.user_id IS NULL
        """
    )
    op.execute("UPDATE rhizome.incident_report SET user_id = '1' WHERE user_id IS NULL")


def downgrade() -> None:
    op.drop_index('ix_incident_report_user_id', table_name='incident_report', schema='rhizome')
    op.drop_column('incident_report', 'user_id', schema='rhizome')
