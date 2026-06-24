"""Add template_file_path to report_templates

Revision ID: 009
Revises: 008
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '009'
down_revision: Union[str, None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'report_templates',
        sa.Column('template_file_path', sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('report_templates', 'template_file_path')
