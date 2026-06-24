"""Expand oauth_account token columns to Text and add token_expires_at

Revision ID: 006
Revises: 005
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'oauth_accounts', 'access_token',
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'oauth_accounts', 'refresh_token',
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        'oauth_accounts',
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('oauth_accounts', 'token_expires_at')
    op.alter_column(
        'oauth_accounts', 'access_token',
        type_=sa.String(2000),
        existing_nullable=True,
    )
    op.alter_column(
        'oauth_accounts', 'refresh_token',
        type_=sa.String(2000),
        existing_nullable=True,
    )
