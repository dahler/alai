"""Add document_folders table and folder_id to attachments

Revision ID: 008
Revises: 007
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_folders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('is_company_folder', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_document_folders_user_id', 'document_folders', ['user_id'])
    op.create_index('ix_document_folders_is_company_folder', 'document_folders', ['is_company_folder'])

    op.add_column(
        'attachments',
        sa.Column('folder_id', sa.Integer(), sa.ForeignKey('document_folders.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_attachments_folder_id', 'attachments', ['folder_id'])


def downgrade() -> None:
    op.drop_index('ix_attachments_folder_id', table_name='attachments')
    op.drop_column('attachments', 'folder_id')
    op.drop_index('ix_document_folders_is_company_folder', table_name='document_folders')
    op.drop_index('ix_document_folders_user_id', table_name='document_folders')
    op.drop_table('document_folders')
