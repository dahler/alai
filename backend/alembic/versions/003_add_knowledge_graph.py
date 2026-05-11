"""Add knowledge graph tables

Revision ID: 003
Revises: 002
Create Date: 2024-01-20 00:00:00.000000

This migration adds:
- entities table for storing extracted entities
- entity_relationships table for storing relationships between entities
- document_entities table for linking documents to entities
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    # Ensure pgvector extension exists
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create entities table
    if not table_exists('entities'):
        op.execute('''
            CREATE TABLE entities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(500) NOT NULL,
                normalized_name VARCHAR(500) NOT NULL,
                entity_type VARCHAR(100) NOT NULL,
                description TEXT,
                aliases TEXT,
                embedding vector(768),
                mention_count INTEGER DEFAULT 1,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            )
        ''')

        # Create indexes for entities
        op.create_index('ix_entities_normalized_name', 'entities', ['normalized_name'])
        op.create_index('ix_entities_entity_type', 'entities', ['entity_type'])
        op.create_index('ix_entities_type_name', 'entities', ['entity_type', 'normalized_name'])

        # Create vector index for entity embeddings
        op.execute('''
            CREATE INDEX ix_entities_embedding
            ON entities
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        ''')

    # Create entity_relationships table
    if not table_exists('entity_relationships'):
        op.execute('''
            CREATE TABLE entity_relationships (
                id SERIAL PRIMARY KEY,
                source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                relation_type VARCHAR(100) NOT NULL,
                target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                confidence FLOAT DEFAULT 1.0,
                source_document_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL,
                source_chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
                context TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
            )
        ''')

        # Create indexes for relationships
        op.create_index('ix_relationships_source_entity_id', 'entity_relationships', ['source_entity_id'])
        op.create_index('ix_relationships_target_entity_id', 'entity_relationships', ['target_entity_id'])
        op.create_index('ix_relationships_relation_type', 'entity_relationships', ['relation_type'])
        op.create_index('ix_relationships_source_document_id', 'entity_relationships', ['source_document_id'])
        op.create_index('ix_relationships_source_relation', 'entity_relationships', ['source_entity_id', 'relation_type'])
        op.create_index('ix_relationships_target_relation', 'entity_relationships', ['target_entity_id', 'relation_type'])
        op.create_index('ix_relationships_triple', 'entity_relationships', ['source_entity_id', 'relation_type', 'target_entity_id'])

    # Create document_entities table
    if not table_exists('document_entities'):
        op.execute('''
            CREATE TABLE document_entities (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
                mention_count INTEGER DEFAULT 1,
                confidence FLOAT DEFAULT 1.0,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
                UNIQUE(document_id, entity_id)
            )
        ''')

        # Create indexes for document_entities
        op.create_index('ix_document_entities_document_id', 'document_entities', ['document_id'])
        op.create_index('ix_document_entities_entity_id', 'document_entities', ['entity_id'])
        op.create_index('ix_document_entities_chunk_id', 'document_entities', ['chunk_id'])


def downgrade() -> None:
    # Drop tables in reverse order of dependencies
    if table_exists('document_entities'):
        op.drop_table('document_entities')

    if table_exists('entity_relationships'):
        op.drop_table('entity_relationships')

    if table_exists('entities'):
        op.drop_table('entities')
