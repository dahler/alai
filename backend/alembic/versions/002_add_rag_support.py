"""Add RAG support with pgvector

Revision ID: 002
Revises: 001
Create Date: 2024-01-15 00:00:00.000000

This migration adds:
- pgvector extension for vector similarity search
- is_admin column to users table
- attachments table (if not exists) with RAG columns
- document_chunks table for storing embeddings
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TEXT


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SELECT EXISTS (SELECT FROM information_schema.columns "
        f"WHERE table_name = '{table_name}' AND column_name = '{column_name}')"
    ))
    return result.scalar()


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = '{table_name}')"
    ))
    return result.scalar()


def index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = '{index_name}')"
    ))
    return result.scalar()


def constraint_exists(constraint_name: str) -> bool:
    """Check if a constraint exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        f"SELECT EXISTS (SELECT FROM information_schema.table_constraints WHERE constraint_name = '{constraint_name}')"
    ))
    return result.scalar()


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Add is_admin to users table if not exists
    if not column_exists('users', 'is_admin'):
        op.add_column('users', sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=False))

    # Handle attachments table
    if table_exists('attachments'):
        # Add new columns if they don't exist
        if not column_exists('attachments', 'user_id'):
            op.add_column('attachments', sa.Column('user_id', sa.Integer(), nullable=True))
            op.create_foreign_key(
                'fk_attachments_user_id',
                'attachments', 'users',
                ['user_id'], ['id'],
                ondelete='SET NULL'
            )
            if not index_exists('ix_attachments_user_id'):
                op.create_index('ix_attachments_user_id', 'attachments', ['user_id'])

        if not column_exists('attachments', 'is_company_doc'):
            op.add_column('attachments', sa.Column('is_company_doc', sa.Boolean(), server_default='false', nullable=False))
            if not index_exists('ix_attachments_is_company_doc'):
                op.create_index('ix_attachments_is_company_doc', 'attachments', ['is_company_doc'])

        if not column_exists('attachments', 'is_embedded'):
            op.add_column('attachments', sa.Column('is_embedded', sa.Boolean(), server_default='false', nullable=False))
    else:
        # Create attachments table from scratch
        op.create_table(
            'attachments',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('message_id', sa.Integer(), nullable=True),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('is_company_doc', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('is_embedded', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('original_filename', sa.String(255), nullable=False),
            sa.Column('content_type', sa.String(100), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=False),
            sa.Column('file_path', sa.String(500), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_attachments_message_id', 'attachments', ['message_id'])
        op.create_index('ix_attachments_user_id', 'attachments', ['user_id'])
        op.create_index('ix_attachments_is_company_doc', 'attachments', ['is_company_doc'])

    # Handle document_chunks table
    if not table_exists('document_chunks'):
        # Create document_chunks table for RAG embeddings using raw SQL for vector type
        op.execute('''
            CREATE TABLE document_chunks (
                id SERIAL PRIMARY KEY,
                attachment_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                is_company_doc BOOLEAN NOT NULL DEFAULT false,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding vector(768) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            )
        ''')

        # Create indexes for document_chunks
        op.create_index('ix_document_chunks_attachment_id', 'document_chunks', ['attachment_id'])
        op.create_index('ix_document_chunks_user_id', 'document_chunks', ['user_id'])
        op.create_index('ix_document_chunks_is_company_doc', 'document_chunks', ['is_company_doc'])

        # Create vector similarity index (IVFFlat)
        op.execute('''
            CREATE INDEX ix_document_chunks_embedding
            ON document_chunks
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        ''')
    else:
        # Table exists, make sure indexes exist
        if not index_exists('ix_document_chunks_attachment_id'):
            op.create_index('ix_document_chunks_attachment_id', 'document_chunks', ['attachment_id'])
        if not index_exists('ix_document_chunks_user_id'):
            op.create_index('ix_document_chunks_user_id', 'document_chunks', ['user_id'])
        if not index_exists('ix_document_chunks_is_company_doc'):
            op.create_index('ix_document_chunks_is_company_doc', 'document_chunks', ['is_company_doc'])
        if not index_exists('ix_document_chunks_embedding'):
            op.execute('''
                CREATE INDEX ix_document_chunks_embedding
                ON document_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            ''')


def downgrade() -> None:
    # Drop document_chunks table if exists
    if table_exists('document_chunks'):
        op.drop_table('document_chunks')

    # Check if attachments table has our new columns and remove them
    if table_exists('attachments'):
        if column_exists('attachments', 'is_embedded'):
            op.drop_column('attachments', 'is_embedded')

        if column_exists('attachments', 'is_company_doc'):
            if index_exists('ix_attachments_is_company_doc'):
                op.drop_index('ix_attachments_is_company_doc', 'attachments')
            op.drop_column('attachments', 'is_company_doc')

        if column_exists('attachments', 'user_id'):
            if index_exists('ix_attachments_user_id'):
                op.drop_index('ix_attachments_user_id', 'attachments')
            if constraint_exists('fk_attachments_user_id'):
                op.drop_constraint('fk_attachments_user_id', 'attachments', type_='foreignkey')
            op.drop_column('attachments', 'user_id')

    # Remove is_admin from users
    if column_exists('users', 'is_admin'):
        op.drop_column('users', 'is_admin')

    # Note: We don't drop the vector extension as other things might depend on it
