"""Add doc_title column to attachments for title-based connection detection

Revision ID: 012
Revises: 011
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'attachments',
        sa.Column('doc_title', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('attachments', 'doc_title')
