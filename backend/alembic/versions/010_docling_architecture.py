"""Docling architecture: sections, summaries, bge-m3 (1024-dim) embeddings

Revision ID: 010
Revises: 009
Create Date: 2026-06-15 00:00:00.000000

Changes:
- Upgrade embedding vectors from 768-dim to 1024-dim (bge-m3)
- Add document_sections table
- Add document_summaries table
- Add section_id, page_start, page_end, heading_context, token_count to chunks
- Add processing_status, version, sections_count to attachments
- Reset is_embedded=false (old 768-dim embeddings are invalid)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Upgrade document_chunks embedding: 768 -> 1024
    # -------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE document_chunks "
        "ADD COLUMN embedding vector(1024)"
    )

    # -------------------------------------------------------------------------
    # 2. Upgrade entities embedding: 768 -> 1024
    # -------------------------------------------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_entities_embedding")
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE entities "
        "ADD COLUMN embedding vector(1024)"
    )

    # -------------------------------------------------------------------------
    # 3. Reset is_embedded — old 768-dim vectors are gone
    # -------------------------------------------------------------------------
    op.execute("UPDATE attachments SET is_embedded = false")

    # -------------------------------------------------------------------------
    # 4. Add new columns to attachments
    # -------------------------------------------------------------------------
    op.add_column(
        'attachments',
        sa.Column(
            'processing_status',
            sa.String(30),
            nullable=True,
            server_default='uploaded',
        ),
    )
    op.add_column(
        'attachments',
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column(
        'attachments',
        sa.Column(
            'sections_count', sa.Integer(), nullable=False, server_default='0'
        ),
    )

    # -------------------------------------------------------------------------
    # 5. Add new columns to document_chunks
    # -------------------------------------------------------------------------
    op.add_column(
        'document_chunks',
        sa.Column('section_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'document_chunks',
        sa.Column(
            'page_start', sa.Integer(), nullable=False, server_default='0'
        ),
    )
    op.add_column(
        'document_chunks',
        sa.Column(
            'page_end', sa.Integer(), nullable=False, server_default='0'
        ),
    )
    op.add_column(
        'document_chunks',
        sa.Column('heading_context', sa.Text(), nullable=True),
    )
    op.add_column(
        'document_chunks',
        sa.Column(
            'token_count', sa.Integer(), nullable=False, server_default='0'
        ),
    )

    # -------------------------------------------------------------------------
    # 6. Create document_sections table
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_sections (
            id SERIAL PRIMARY KEY,
            attachment_id INTEGER NOT NULL
                REFERENCES attachments(id) ON DELETE CASCADE,
            parent_section_id INTEGER
                REFERENCES document_sections(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            section_index INTEGER NOT NULL DEFAULT 0,
            content TEXT,
            page_start INTEGER NOT NULL DEFAULT 0,
            page_end INTEGER NOT NULL DEFAULT 0,
            summary TEXT,
            summary_embedding vector(1024),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_sections_attachment_id "
        "ON document_sections(attachment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_sections_parent_section_id "
        "ON document_sections(parent_section_id)"
    )

    # -------------------------------------------------------------------------
    # 7. Create document_summaries table
    # -------------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_summaries (
            id SERIAL PRIMARY KEY,
            attachment_id INTEGER NOT NULL
                REFERENCES attachments(id) ON DELETE CASCADE,
            section_id INTEGER
                REFERENCES document_sections(id) ON DELETE CASCADE,
            summary_type VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_summaries_attachment_id "
        "ON document_summaries(attachment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_summaries_section_id "
        "ON document_summaries(section_id)"
    )

    # -------------------------------------------------------------------------
    # 8. Add FK from document_chunks.section_id -> document_sections.id
    # -------------------------------------------------------------------------
    op.create_foreign_key(
        'fk_document_chunks_section_id',
        'document_chunks',
        'document_sections',
        ['section_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_document_chunks_section_id',
        'document_chunks',
        ['section_id'],
    )

    # -------------------------------------------------------------------------
    # 9. Recreate IVFFlat indexes (need rows first — created empty here)
    # -------------------------------------------------------------------------
    # document_chunks embedding index will be created after data is loaded
    # because IVFFlat requires at least `lists` rows.
    # We create a plain btree placeholder that gets replaced on first embed.
    # For now just note: run after embedding:
    #   CREATE INDEX ix_document_chunks_embedding ON document_chunks
    #   USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_section_id")
    op.execute(
        "ALTER TABLE document_chunks "
        "DROP CONSTRAINT IF EXISTS fk_document_chunks_section_id"
    )
    op.drop_column('document_chunks', 'token_count')
    op.drop_column('document_chunks', 'heading_context')
    op.drop_column('document_chunks', 'page_end')
    op.drop_column('document_chunks', 'page_start')
    op.drop_column('document_chunks', 'section_id')

    op.drop_column('attachments', 'sections_count')
    op.drop_column('attachments', 'version')
    op.drop_column('attachments', 'processing_status')

    op.execute("DROP TABLE IF EXISTS document_summaries")
    op.execute("DROP TABLE IF EXISTS document_sections")

    # Restore 768-dim embedding columns (data will be lost)
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN embedding vector(768)"
    )
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE entities ADD COLUMN embedding vector(768)")
