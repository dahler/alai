"""Add document_connections table for explicit cross-document references

Revision ID: 011
Revises: 010
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_connections',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_id', sa.Integer(),
                  sa.ForeignKey('attachments.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('target_id', sa.Integer(),
                  sa.ForeignKey('attachments.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('mention_count', sa.Integer(), default=1),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint('source_id', 'target_id',
                            name='uq_doc_connection'),
    )


def downgrade() -> None:
    op.drop_table('document_connections')
