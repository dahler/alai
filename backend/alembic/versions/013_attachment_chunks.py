"""Add attachment_chunks table for persisted document chunking

Revision ID: 013
Revises: 012
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'attachment_chunks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'attachment_id',
            sa.Integer(),
            sa.ForeignKey('attachments.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('total_chunks', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
    )
    op.create_index(
        'ix_attachment_chunks_attachment_id',
        'attachment_chunks',
        ['attachment_id'],
    )


def downgrade():
    op.drop_index('ix_attachment_chunks_attachment_id',
                  table_name='attachment_chunks')
    op.drop_table('attachment_chunks')
