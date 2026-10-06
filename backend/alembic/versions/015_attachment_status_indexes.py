"""Add indexes on Attachment.processing_status and Attachment.is_embedded

Revision ID: 015
Revises: 014
Create Date: 2026-10-06

These columns are used as filter criteria in attachment list queries but
had no index, causing full table scans as the uploads table grows.
"""
from alembic import op

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_attachments_processing_status',
        'attachments',
        ['processing_status'],
    )
    op.create_index(
        'ix_attachments_is_embedded',
        'attachments',
        ['is_embedded'],
    )


def downgrade():
    op.drop_index('ix_attachments_is_embedded', table_name='attachments')
    op.drop_index(
        'ix_attachments_processing_status', table_name='attachments'
    )
