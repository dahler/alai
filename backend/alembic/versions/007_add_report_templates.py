"""Add report_templates table

Revision ID: 007
Revises: 006
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'report_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('format', sa.String(10), nullable=False),
        sa.Column('sections_json', sa.Text(), nullable=False),
        sa.Column('keywords', sa.String(500), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('is_company_wide', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_report_templates_owner_id', 'report_templates', ['owner_id'])
    op.create_index('ix_report_templates_is_company_wide', 'report_templates', ['is_company_wide'])


def downgrade() -> None:
    op.drop_index('ix_report_templates_is_company_wide', table_name='report_templates')
    op.drop_index('ix_report_templates_owner_id', table_name='report_templates')
    op.drop_table('report_templates')
