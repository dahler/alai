"""Add graph_status column to attachments

Revision ID: 005
Revises: 004
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('attachments', sa.Column('graph_status', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('attachments', 'graph_status')
