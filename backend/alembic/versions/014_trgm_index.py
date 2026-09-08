"""Add pg_trgm extension and GIN trigram index on document_chunks.chunk_text

Revision ID: 014
Revises: 013
Create Date: 2026-09-08

Enables PostgreSQL trigram similarity search (pg_trgm) so the retrieval
pipeline can pre-filter chunk candidates by keyword similarity before the
vector search step, replacing the post-hoc Python BM25 re-ranker.
"""
from alembic import op

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_chunk_text_trgm
        ON document_chunks
        USING GIN (chunk_text gin_trgm_ops)
        """
    )


def downgrade():
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_chunk_text_trgm"
    )
    # Extension is intentionally NOT dropped — other tables may use it.
