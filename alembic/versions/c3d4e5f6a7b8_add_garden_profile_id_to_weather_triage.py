"""add garden_profile_id to weather_snapshot and triage_snapshot

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('weather_snapshot', sa.Column('garden_profile_id', sa.String(), nullable=True), schema='rhizome')
    op.create_index('ix_weather_snapshot_garden_profile_id', 'weather_snapshot', ['garden_profile_id'], unique=False, schema='rhizome')
    op.create_foreign_key(
        'fk_weather_snapshot_garden_profile_id', 'weather_snapshot', 'garden_profile',
        ['garden_profile_id'], ['id'], source_schema='rhizome', referent_schema='rhizome',
    )

    op.add_column('triage_snapshot', sa.Column('garden_profile_id', sa.String(), nullable=True), schema='rhizome')
    op.create_index('ix_triage_snapshot_garden_profile_id', 'triage_snapshot', ['garden_profile_id'], unique=False, schema='rhizome')
    op.create_foreign_key(
        'fk_triage_snapshot_garden_profile_id', 'triage_snapshot', 'garden_profile',
        ['garden_profile_id'], ['id'], source_schema='rhizome', referent_schema='rhizome',
    )

    # WeatherSnapshot/TriageSnapshot were global singletons before this migration —
    # there's no way to know who a pre-existing row "belonged" to. Backfill to the
    # single bootstrapped user's garden profile, matching the pattern used for
    # InteractionRecord/IncidentReport (a1b2c3d4e5f6, b2c3d4e5f6a7).
    op.execute(
        """
        UPDATE rhizome.weather_snapshot
        SET garden_profile_id = (
            SELECT id FROM rhizome.garden_profile WHERE user_id = '1' LIMIT 1
        )
        WHERE garden_profile_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE rhizome.triage_snapshot
        SET garden_profile_id = (
            SELECT id FROM rhizome.garden_profile WHERE user_id = '1' LIMIT 1
        )
        WHERE garden_profile_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint('fk_triage_snapshot_garden_profile_id', 'triage_snapshot', schema='rhizome', type_='foreignkey')
    op.drop_index('ix_triage_snapshot_garden_profile_id', table_name='triage_snapshot', schema='rhizome')
    op.drop_column('triage_snapshot', 'garden_profile_id', schema='rhizome')

    op.drop_constraint('fk_weather_snapshot_garden_profile_id', 'weather_snapshot', schema='rhizome', type_='foreignkey')
    op.drop_index('ix_weather_snapshot_garden_profile_id', table_name='weather_snapshot', schema='rhizome')
    op.drop_column('weather_snapshot', 'garden_profile_id', schema='rhizome')
