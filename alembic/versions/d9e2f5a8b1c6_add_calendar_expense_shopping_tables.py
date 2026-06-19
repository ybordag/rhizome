"""add calendar_annotation, project_expense, shopping_item tables

Revision ID: d9e2f5a8b1c6
Revises: b7c4e1f92a3d
Create Date: 2026-06-19 16:01:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd9e2f5a8b1c6'
down_revision: Union[str, Sequence[str], None] = 'b7c4e1f92a3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'calendar_annotation',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('color', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='rhizome',
    )
    op.create_index('ix_calendar_annotation_user_date', 'calendar_annotation',
                    ['user_id', 'date'], schema='rhizome')

    op.create_table(
        'project_expense',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('estimated_cost', sa.Float(), nullable=True),
        sa.Column('actual_cost', sa.Float(), nullable=True),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit', sa.Text(), nullable=True),
        sa.Column('supplier', sa.Text(), nullable=True),
        sa.Column('purchased_at', sa.Date(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='needed'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['rhizome.gardening_project.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='rhizome',
    )
    op.create_index('ix_project_expense_user_id', 'project_expense', ['user_id'], schema='rhizome')
    op.create_index('ix_project_expense_project_id', 'project_expense', ['project_id'], schema='rhizome')

    op.create_table(
        'shopping_item',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('project_id', sa.String(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit', sa.Text(), nullable=True),
        sa.Column('estimated_cost', sa.Float(), nullable=True),
        sa.Column('supplier', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='needed'),
        sa.Column('priority', sa.Text(), nullable=False, server_default='normal'),
        sa.Column('expense_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['rhizome.gardening_project.id']),
        sa.ForeignKeyConstraint(['expense_id'], ['rhizome.project_expense.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='rhizome',
    )
    op.create_index('ix_shopping_item_user_id', 'shopping_item', ['user_id'], schema='rhizome')
    op.create_index('ix_shopping_item_project_id', 'shopping_item', ['project_id'], schema='rhizome')
    op.create_index('ix_shopping_item_status', 'shopping_item', ['status'], schema='rhizome')


def downgrade() -> None:
    op.drop_index('ix_shopping_item_status', table_name='shopping_item', schema='rhizome')
    op.drop_index('ix_shopping_item_project_id', table_name='shopping_item', schema='rhizome')
    op.drop_index('ix_shopping_item_user_id', table_name='shopping_item', schema='rhizome')
    op.drop_table('shopping_item', schema='rhizome')
    op.drop_index('ix_project_expense_project_id', table_name='project_expense', schema='rhizome')
    op.drop_index('ix_project_expense_user_id', table_name='project_expense', schema='rhizome')
    op.drop_table('project_expense', schema='rhizome')
    op.drop_index('ix_calendar_annotation_user_date', table_name='calendar_annotation', schema='rhizome')
    op.drop_table('calendar_annotation', schema='rhizome')
