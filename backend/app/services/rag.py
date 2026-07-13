"""
RAG service — structure-aware document ingestion and retrieval.

Ingestion pipeline:
  1. Parse document with DoclingService (headings, tables, sections)
  2. Store section hierarchy in document_sections
  3. Generate section summaries + embed them
  4. Structure-aware chunking (section-first, tables intact)
  5. Embed chunks with heading context prepended
  6. Store chunks in document_chunks

Retrieval pipeline:
  1. Embed query
  2. Search section summary embeddings → identify relevant sections
  3. Search chunks within those sections (vector)
  4. BM25 keyword re-rank across candidates
  5. Expand context with neighbouring chunks
"""

import re
import time
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, and_, tuple_

from app.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.document_section import DocumentSection
from app.models.document_summary import DocumentSummary
from app.models.attachment import Attachment
from app.models.document_connection import DocumentConnection
from app.services.embedding import EmbeddingService
from app.services.docling_service import DoclingService, ParsedSection
from app.services.summarization_service import SummarizationService


def log(message: str) -> None:
    import time
    print(f"[{time.strftime('%H:%M:%S')}] [RAG] {message}")


def _mem_mb() -> int:
    try:
        import psutil
        import os
        return psutil.Process(os.getpid()).memory_info().rss // (1024 * 1024)
    except Exception:
        return -1


# Approximate characters per token for bge-m3 / typical text
_CHARS_PER_TOKEN = 4
_TARGET_TOKENS_MIN = 500
_TARGET_TOKENS_MAX = 1000
_CHUNK_MAX_CHARS = _TARGET_TOKENS_MAX * _CHARS_PER_TOKEN   # 4000
_CHUNK_MIN_CHARS = _TARGET_TOKENS_MIN * _CHARS_PER_TOKEN   # 2000
_CHUNK_OVERLAP_CHARS = 200


def _title_ngrams(title: str, window: int = 5) -> list[str]:
    """
    Build sliding n-gram phrases from a document title for citation matching.

    A 5-word window from "Bank Indonesia Regulation Number 2 of 2024
    concerning Information System Security" produces phrases like
    "regulation number 2 of 2024" which will match the citation text
    regardless of surrounding words.
    """
    words = re.findall(r'[\w]+', title.lower())
    if len(words) <= window:
        return [' '.join(words)] if len(words) >= 3 else []
    return [' '.join(words[i: i + window]) for i in range(len(words) - window + 1)]


class RAGService:
    """Structure-aware RAG: ingest, embed, and retrieve documents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.embedding = EmbeddingService()
        self.docling = DoclingService()
        self.summarizer = SummarizationService()
        self.top_k = settings.RAG_TOP_K

    # ==================================================================
    # Ingestion
    # ==================================================================

    async def embed_document(
        self,
        attachment_id: int,
        user_id: Optional[int] = None,
        is_company_doc: bool = False,
        parsed_document=None,
    ) -> dict:
        """
        Full ingestion pipeline: parse → section → summarise → chunk → embed.

        Returns a stats dict with keys:
          sections_created, chunks_created, processing_time, error (if any)
        """
        log("=" * 50)
        log("DOCUMENT INGESTION")
        log("=" * 50)
        log(f"MEM start: {_mem_mb()} MB")
        t0 = time.time()
        stats: dict = {
            "sections_created": 0,
            "chunks_created": 0,
            "processing_time": 0.0,
        }

        result = await self.db.execute(
            select(Attachment).where(Attachment.id == attachment_id)
        )
        attachment = result.scalar_one_or_none()
        if not attachment:
            return {"error": "Attachment not found", **stats}

        log(f"Document: {attachment.original_filename}")

        # ------------------------------------------------------------------
        # Phase 1: Parse
        # ------------------------------------------------------------------
        await self._set_status(attachment, "parsing")
        if parsed_document is not None:
            parsed = parsed_document
        else:
            parsed = await self.docling.parse(
                attachment.file_path,
                original_name=attachment.original_filename or "",
            )
        if not parsed:
            await self._set_status(attachment, "failed")
            return {"error": "Failed to parse document", **stats}
        log(f"MEM after parse: {_mem_mb()} MB")

        log(
            f"✓ Parsed: {len(parsed.sections)} sections, "
            f"{parsed.page_count} pages"
        )

        # ------------------------------------------------------------------
        # Phase 2: Store sections
        # ------------------------------------------------------------------
        await self._set_status(attachment, "sectioning")

        # Delete existing sections/chunks for this doc
        await self.db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.attachment_id == attachment_id
            )
        )
        await self.db.execute(
            delete(DocumentSection).where(
                DocumentSection.attachment_id == attachment_id
            )
        )
        await self.db.execute(
            delete(DocumentSummary).where(
                DocumentSummary.attachment_id == attachment_id
            )
        )

        section_records: list[DocumentSection] = []
        for sec in parsed.sections:
            rec = DocumentSection(
                attachment_id=attachment_id,
                title=sec.title,
                level=sec.level,
                section_index=sec.section_index,
                content=sec.content,
                page_start=sec.page_start,
                page_end=sec.page_end,
            )
            self.db.add(rec)
            section_records.append(rec)

        await self.db.flush()  # get section IDs
        stats["sections_created"] = len(section_records)

        # Embed section title + content so section-first retrieval works.
        # No LLM summarization needed — bge-m3 embeds the raw text directly.
        sec_texts = [
            f"{sec.title}\n\n{(sec.content or '')[:2000]}"
            for sec in parsed.sections
        ]
        sec_embeddings = await self.embedding.embed_texts(sec_texts)
        for rec, emb in zip(section_records, sec_embeddings):
            if emb is not None:
                rec.summary_embedding = emb
        del sec_texts, sec_embeddings
        await self.db.flush()

        # Snapshot IDs now while objects are loaded — after any commit()
        # SQLAlchemy expires ORM objects, and accessing .id would trigger
        # a lazy SELECT round-trip per row under memory pressure.
        section_id_map: list[tuple[int, object]] = [
            (rec.id, sec)
            for rec, sec in zip(section_records, parsed.sections)
        ]
        del section_records  # no longer needed as ORM objects

        # ------------------------------------------------------------------
        # Phase 3: Summaries
        # ------------------------------------------------------------------
        await self._set_status(attachment, "summarizing")
        log(f"MEM before summarize: {_mem_mb()} MB")

        doc_summary_text = await self.summarizer.summarize_document(
            title=parsed.title,
            content=parsed.full_markdown,
        )
        if doc_summary_text:
            self.db.add(DocumentSummary(
                attachment_id=attachment_id,
                summary_type="document",
                content=doc_summary_text,
            ))

        # Section-level summarization disabled — each section's heading +
        # content is sufficient context for retrieval without loading the LLM
        # N times per document.

        await self.db.flush()

        # ------------------------------------------------------------------
        # Phase 4 + 5: Chunk + embed in sub-batches to cap memory usage
        # ------------------------------------------------------------------
        await self._set_status(attachment, "embedding")
        log(f"MEM before embed: {_mem_mb()} MB")

        _EMBED_BATCH = 200  # embed 200 chunks at a time, flush, repeat

        # Extract only primitive values — no SQLAlchemy objects, no
        # ParsedSection objects — so parsed + section_id_map can be
        # freed before the embedding loop begins.
        # tuple: (section_id, raw_text, heading_ctx, page_start, page_end)
        pending: list[tuple] = []
        for sid, sec in section_id_map:
            heading_ctx = _build_heading_context(parsed.title, sec)
            ps, pe = sec.page_start, sec.page_end
            for raw_text in _chunk_section(sec.content):
                pending.append((sid, raw_text, heading_ctx, ps, pe))

        # Save full text and title for connection detection before freeing parsed
        full_text = parsed.full_markdown or ""
        doc_title = parsed.title or ""

        # Free large objects before embedding — parsed.full_markdown and
        # all section content can be several MB for big documents.
        del section_id_map, parsed
        log(
            f"MEM after pending build: {_mem_mb()} MB"
            f"  ({len(pending)} chunks to embed)"
        )

        chunk_count = 0
        for batch_start in range(0, len(pending), _EMBED_BATCH):
            batch = pending[batch_start: batch_start + _EMBED_BATCH]
            log(f"MEM before embed batch {batch_start//200}: {_mem_mb()} MB")

            texts_to_embed = [
                f"{hctx}\n\n{rt}" if hctx else rt
                for _, rt, hctx, _, _ in batch
            ]
            embeddings = await self.embedding.embed_texts(texts_to_embed)
            log(f"MEM after embed batch {batch_start//200}: {_mem_mb()} MB")
            del texts_to_embed

            for (sid, raw_text, heading_ctx, ps, pe), emb in zip(
                batch, embeddings
            ):
                if emb is None:
                    continue
                self.db.add(DocumentChunk(
                    attachment_id=attachment_id,
                    user_id=user_id if not is_company_doc else None,
                    is_company_doc=is_company_doc,
                    section_id=sid,
                    chunk_index=chunk_count,
                    chunk_text=raw_text,
                    heading_context=heading_ctx,
                    page_start=ps,
                    page_end=pe,
                    token_count=len(raw_text) // _CHARS_PER_TOKEN,
                    embedding=emb,
                ))
                chunk_count += 1

            del embeddings
            await self.db.flush()
            self.db.expire_all()

        del pending
        stats["chunks_created"] = chunk_count
        log(f"MEM after embed: {_mem_mb()} MB")

        # ------------------------------------------------------------------
        # Finalise
        # ------------------------------------------------------------------
        attachment.is_embedded = True
        attachment.user_id = user_id
        attachment.is_company_doc = is_company_doc
        attachment.sections_count = stats["sections_created"]
        attachment.processing_status = "done"
        if doc_title:
            attachment.doc_title = doc_title

        # Detect explicit cross-document references in the parsed text
        await self._detect_connections(
            attachment_id, parsed_text=full_text
        )

        await self.db.commit()

        stats["processing_time"] = time.time() - t0
        log(
            f"✓ Done: {stats['sections_created']} sections, "
            f"{stats['chunks_created']} chunks "
            f"in {stats['processing_time']:.2f}s"
        )
        return stats

    # ==================================================================
    # Search
    # ==================================================================

    async def search(
        self,
        query: str,
        user_id: Optional[int] = None,
        top_k: Optional[int] = None,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Section-first hybrid retrieval.

        Steps:
          1. Embed query
          2. Find top sections by summary embedding similarity
          3. Search chunks within those sections (vector)
          4. BM25 re-rank
          5. Expand with neighbouring chunks
        """
        top_k = top_k or self.top_k
        log(f"SEARCH: {query[:80]}")

        query_emb = await self.embedding.embed_text(query)
        if not query_emb:
            log("✗ Failed to embed query")
            return []

        access = _access_filter(user_id)

        # ------------------------------------------------------------------
        # Step 1: Find relevant sections via summary embedding
        # ------------------------------------------------------------------
        section_q = (
            select(
                DocumentSection.id,
                DocumentSection.attachment_id,
                DocumentSection.summary_embedding.cosine_distance(
                    query_emb
                ).label("sec_dist"),
            )
            .join(
                Attachment,
                Attachment.id == DocumentSection.attachment_id,
            )
            .where(
                DocumentSection.summary_embedding.isnot(None),
                _attachment_access_filter(user_id),
            )
            .order_by("sec_dist")
            .limit(top_k * 3)
        )
        if source_filter:
            section_q = section_q.where(
                Attachment.original_filename.ilike(f"%{source_filter}%")
            )
        sec_rows = (await self.db.execute(section_q)).all()
        relevant_section_ids = [r.id for r in sec_rows]

        # Expand to all sections in the same numbered group (e.g. all "2.1.X")
        expanded_section_ids = await self._expand_section_groups(
            relevant_section_ids
        )
        was_expanded = len(expanded_section_ids) > len(relevant_section_ids)
        if was_expanded:
            log(
                f"Section group expanded: "
                f"{len(relevant_section_ids)} -> "
                f"{len(expanded_section_ids)} sections"
            )
        relevant_section_ids = expanded_section_ids

        # ------------------------------------------------------------------
        # Step 2: Search chunks (vector) — prefer relevant sections
        # ------------------------------------------------------------------
        chunk_q = (
            select(
                DocumentChunk,
                Attachment.original_filename,
                DocumentChunk.embedding.cosine_distance(query_emb).label(
                    "distance"
                ),
            )
            .join(Attachment, Attachment.id == DocumentChunk.attachment_id)
            .where(access)
        )
        if source_filter:
            chunk_q = chunk_q.where(
                Attachment.original_filename.ilike(f"%{source_filter}%")
            )

        # When a full group was expanded fetch enough to cover all sections
        fetch_k = (
            max(top_k * 8, len(relevant_section_ids) * 2)
            if was_expanded
            else top_k * 4
        )
        if relevant_section_ids:
            in_sections = chunk_q.where(
                DocumentChunk.section_id.in_(relevant_section_ids)
            ).order_by("distance").limit(fetch_k)
            rows = (await self.db.execute(in_sections)).all()
            if len(rows) < top_k:
                # Supplement with global search
                global_q = chunk_q.order_by("distance").limit(
                    fetch_k - len(rows)
                )
                extra = (await self.db.execute(global_q)).all()
                seen = {r[0].id for r in rows}
                rows += [r for r in extra if r[0].id not in seen]
        else:
            rows = (
                await self.db.execute(
                    chunk_q.order_by("distance").limit(fetch_k)
                )
            ).all()

        if not rows:
            return []

        # ------------------------------------------------------------------
        # Step 3: BM25 re-rank
        # ------------------------------------------------------------------
        rerank_k = min(top_k * 2, len(rows)) if was_expanded else top_k
        rows = _bm25_rerank(query, rows, rerank_k)

        # ------------------------------------------------------------------
        # Step 4: Expand context
        # When the full section group was returned, each chunk is already part
        # of a comprehensive set — skip adjacent expansion to avoid pulling in
        # unrelated content from neighbouring sections.
        # ------------------------------------------------------------------
        if was_expanded:
            expanded_texts = [chunk.chunk_text or "" for chunk, _, _ in rows]
        else:
            expanded_texts = await self._expand_by_section(rows)

        # ------------------------------------------------------------------
        # Step 5: Build results
        # ------------------------------------------------------------------
        results = []
        for i, (chunk, filename, distance) in enumerate(rows):
            results.append({
                "chunk_id": chunk.id,
                "chunk_text": expanded_texts[i],
                "chunk_index": chunk.chunk_index,
                "heading_context": chunk.heading_context,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "similarity": round(1 - distance, 4),
                "attachment_id": chunk.attachment_id,
                "filename": filename or "Unknown",
                "is_company_doc": chunk.is_company_doc,
                "section_id": chunk.section_id,
            })
            log(
                f"  [{1 - distance:.2%}] {filename} "
                f"(chunk {chunk.chunk_index}, "
                f"{len(expanded_texts[i])} chars expanded)"
            )

        # ------------------------------------------------------------------
        # Step 6: Augment with chunks from explicitly connected documents
        # ------------------------------------------------------------------
        results = await self._augment_with_connections(
            query_emb, results, user_id, top_k
        )

        return results

    # ==================================================================
    # Helpers
    # ==================================================================

    async def _detect_connections(
        self, attachment_id: int, parsed_text: str
    ) -> None:
        """
        Scan parsed_text for references to other documents using title-based
        n-gram matching. For each other embedded document, generates 5-word
        sliding windows from its stored title and checks if any window appears
        verbatim in the text. Falls back to filename-stem matching for docs
        without a stored title.
        """
        if not parsed_text:
            return

        rows = (await self.db.execute(
            select(Attachment.id, Attachment.original_filename, Attachment.doc_title)
            .where(
                Attachment.is_embedded.is_(True),
                Attachment.id != attachment_id,
            )
        )).all()

        if not rows:
            return

        text_lower = parsed_text.lower()
        found: dict[int, int] = {}  # target_id -> mention_count

        for doc_id, filename, doc_title in rows:
            count = 0

            if doc_title and len(doc_title) >= 10:
                # Title-based: sliding 5-word n-gram match
                phrases = _title_ngrams(doc_title, window=5)
                count = sum(text_lower.count(p) for p in phrases)
            else:
                # Fallback: filename stem match
                stem = re.sub(r'\.[^.]+$', '', filename).lower().strip()
                if len(stem) >= 4:
                    count = text_lower.count(stem)

            if count > 0:
                found[doc_id] = count

        if not found:
            return

        await self.db.execute(
            delete(DocumentConnection).where(
                DocumentConnection.source_id == attachment_id
            )
        )
        for target_id, mention_count in found.items():
            self.db.add(DocumentConnection(
                source_id=attachment_id,
                target_id=target_id,
                mention_count=mention_count,
            ))

        log(
            f"✓ Document connections detected: "
            f"{len(found)} reference(s) from attachment {attachment_id}"
        )
        await self.db.flush()

    async def _augment_with_connections(
        self,
        query_emb: list,
        results: list[dict],
        user_id: Optional[int],
        top_k: int,
    ) -> list[dict]:
        """
        For documents already in results, find explicitly connected documents
        and fetch their most relevant chunks for the query.
        """
        if not results:
            return results

        source_ids = list({r["attachment_id"] for r in results})

        # Find connected documents not already in results
        conn_rows = (await self.db.execute(
            select(DocumentConnection.target_id)
            .where(DocumentConnection.source_id.in_(source_ids))
        )).scalars().all()

        already_fetched = set(source_ids)
        connected_ids = [t for t in set(conn_rows) if t not in already_fetched]

        if not connected_ids:
            return results

        log(f"Connected docs to augment: {connected_ids}")

        # Fetch top-2 chunks per connected document most relevant to query
        access = _access_filter(user_id)
        extra_rows = (await self.db.execute(
            select(
                DocumentChunk,
                Attachment.original_filename,
                DocumentChunk.embedding.cosine_distance(query_emb).label(
                    "distance"
                ),
            )
            .join(Attachment, Attachment.id == DocumentChunk.attachment_id)
            .where(
                access,
                DocumentChunk.attachment_id.in_(connected_ids),
            )
            .order_by("distance")
            .limit(top_k)
        )).all()

        for chunk, filename, distance in extra_rows:
            results.append({
                "chunk_id": chunk.id,
                "chunk_text": chunk.chunk_text or "",
                "chunk_index": chunk.chunk_index,
                "heading_context": chunk.heading_context,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "similarity": round(1 - distance, 4),
                "attachment_id": chunk.attachment_id,
                "filename": filename or "Unknown",
                "is_company_doc": chunk.is_company_doc,
                "section_id": chunk.section_id,
                "via_connection": True,
            })
            log(
                f"  [connected] [{1 - distance:.2%}] {filename} "
                f"chunk {chunk.chunk_index}"
            )

        return results

    async def _expand_section_groups(
        self,
        section_ids: list[int],
    ) -> list[int]:
        """
        Expand matched section IDs to include ALL sections in the same
        numbered group (e.g. all "2.1 / 2.1.X" sections).

        For sections WITH a numbered prefix ("2.1.1 ...") the group prefix
        is extracted directly.  For sections WITHOUT a numbered prefix
        ("c) Analisis risiko") we walk backwards in section_index order to
        find the nearest numbered ancestor and use its group prefix — so
        unnumbered sub-bullets are automatically pulled into the right group.
        """
        if not section_ids:
            return section_ids

        rows = (await self.db.execute(
            select(
                DocumentSection.id,
                DocumentSection.attachment_id,
                DocumentSection.section_index,
                DocumentSection.title,
            ).where(DocumentSection.id.in_(section_ids))
        )).all()

        expanded: set[int] = set(section_ids)

        # Group matched rows by attachment so we only fetch all_secs once
        by_att: dict[int, list] = {}
        for row in rows:
            by_att.setdefault(row.attachment_id, []).append(row)

        for att_id, att_rows in by_att.items():
            all_secs = list((await self.db.execute(
                select(
                    DocumentSection.id,
                    DocumentSection.section_index,
                    DocumentSection.title,
                ).where(
                    DocumentSection.attachment_id == att_id
                ).order_by(DocumentSection.section_index)
            )).all())

            done: set[str] = set()  # prefixes already expanded for this att

            for row in att_rows:
                prefix = _section_group_prefix(row.title)
                if prefix is None:
                    # Unnumbered section — inherit prefix from nearest
                    # numbered section above it
                    prefix = _nearest_group_prefix(
                        row.section_index, all_secs
                    )
                if prefix is None or prefix in done:
                    continue
                done.add(prefix)

                group_start: Optional[int] = None
                group_end: int = (
                    all_secs[-1].section_index
                    if all_secs else row.section_index
                )

                for s in all_secs:
                    if _is_group_header(s.title, prefix):
                        group_start = s.section_index
                    elif (
                        group_start is not None
                        and _is_sibling_or_higher(s.title, prefix)
                    ):
                        group_end = s.section_index - 1
                        break

                if group_start is None:
                    group_start = row.section_index

                for s in all_secs:
                    if group_start <= s.section_index <= group_end:
                        expanded.add(s.id)

        return list(expanded)

    async def _expand_by_section(
        self,
        rows: list,
        min_chars: int = 2000,
        fallback_window: int = 2,
    ) -> list[str]:
        """
        For each result chunk fetch ALL chunks that share the same section_id
        (same heading/subheading), concatenated in chunk_index order.

        If the merged section text is still below `min_chars` (e.g. the section
        is a single bullet point), supplement with up to `fallback_window`
        neighbouring chunks so the LLM has enough context to answer.
        """
        if not rows:
            return []

        # --- Step 1: fetch all chunks in matched sections ---
        section_ids = {
            chunk.section_id
            for chunk, _, _ in rows
            if chunk.section_id is not None
        }
        section_chunks: dict[int, list[str]] = {}
        if section_ids:
            q = (
                select(
                    DocumentChunk.section_id,
                    DocumentChunk.chunk_index,
                    DocumentChunk.chunk_text,
                )
                .where(DocumentChunk.section_id.in_(list(section_ids)))
                .order_by(
                    DocumentChunk.section_id,
                    DocumentChunk.chunk_index,
                )
            )
            for row in (await self.db.execute(q)).all():
                section_chunks.setdefault(row.section_id, []).append(
                    row.chunk_text or ""
                )

        # --- Step 2: build per-row section text, note which need fallback ---
        section_texts: list[str] = []
        needs_fallback: list[bool] = []
        for chunk, _, _ in rows:
            if chunk.section_id and chunk.section_id in section_chunks:
                text = "\n\n".join(
                    t for t in section_chunks[chunk.section_id] if t.strip()
                )
            else:
                text = chunk.chunk_text or ""
            section_texts.append(text)
            needs_fallback.append(len(text) < min_chars)

        # --- Step 3: fetch neighbours for short sections in one query ---
        needed: set[tuple] = set()
        result_keys = {
            (chunk.attachment_id, chunk.chunk_index)
            for chunk, _, _ in rows
        }
        for (chunk, _, _), short in zip(rows, needs_fallback):
            if not short:
                continue
            for delta in range(-fallback_window, fallback_window + 1):
                if delta == 0:
                    continue
                key = (chunk.attachment_id, chunk.chunk_index + delta)
                if key not in result_keys:
                    needed.add(key)

        neighbor_map: dict[tuple, str] = {}
        if needed:
            q = (
                select(
                    DocumentChunk.attachment_id,
                    DocumentChunk.chunk_index,
                    DocumentChunk.chunk_text,
                )
                .where(
                    tuple_(
                        DocumentChunk.attachment_id,
                        DocumentChunk.chunk_index,
                    ).in_(list(needed))
                )
            )
            for row in (await self.db.execute(q)).all():
                neighbor_map[
                    (row.attachment_id, row.chunk_index)
                ] = row.chunk_text or ""

        # --- Step 4: supplement short sections with neighbours ---
        expanded: list[str] = []
        for (chunk, _, _), text, short in zip(
            rows, section_texts, needs_fallback
        ):
            if not short:
                expanded.append(text)
                continue
            parts: list[str] = []
            for delta in range(-fallback_window, fallback_window + 1):
                key = (chunk.attachment_id, chunk.chunk_index + delta)
                if delta == 0:
                    neighbour = text
                else:
                    neighbour = neighbor_map.get(key, "")
                if neighbour.strip():
                    parts.append(neighbour)
            expanded.append("\n\n".join(parts))

        return expanded

    async def _expand_neighbors(
        self,
        rows: list,
        window: int = 1,
    ) -> list[str]:
        """
        For each result chunk fetch up to `window` chunks before and after it
        (same attachment_id, adjacent chunk_index) and concatenate the texts.

        Returns one expanded string per row, in the same order as `rows`.
        """
        if not rows:
            return []

        # Index of chunks already in the result set — their text is known
        result_map: dict[tuple, str] = {
            (c.attachment_id, c.chunk_index): c.chunk_text or ""
            for c, _, _ in rows
        }

        # Collect neighbour keys that are NOT already in results
        needed: set[tuple] = set()
        for chunk, _, _ in rows:
            for delta in range(-window, window + 1):
                if delta == 0:
                    continue
                key = (chunk.attachment_id, chunk.chunk_index + delta)
                if key not in result_map:
                    needed.add(key)

        # Fetch all neighbours in one query
        neighbor_map: dict[tuple, str] = {}
        if needed:
            q = select(
                DocumentChunk.attachment_id,
                DocumentChunk.chunk_index,
                DocumentChunk.chunk_text,
            ).where(
                tuple_(
                    DocumentChunk.attachment_id,
                    DocumentChunk.chunk_index,
                ).in_(list(needed))
            )
            for row in (await self.db.execute(q)).all():
                neighbor_map[
                    (row.attachment_id, row.chunk_index)
                ] = row.chunk_text or ""

        # Merge result_map and neighbor_map for lookup
        all_texts = {**result_map, **neighbor_map}

        # Build expanded text for each row
        expanded: list[str] = []
        for chunk, _, _ in rows:
            parts: list[str] = []
            for delta in range(-window, window + 1):
                key = (chunk.attachment_id, chunk.chunk_index + delta)
                text = all_texts.get(key, "")
                if text.strip():
                    parts.append(text)
            expanded.append("\n\n".join(parts))

        return expanded

    async def reembed_sections(
        self, attachment_id: Optional[int] = None
    ) -> dict:
        """
        Backfill summary_embedding for sections that have none.

        Pass attachment_id to fix one document, or None to fix all.
        """
        from sqlalchemy import update as sa_update

        q = select(
            DocumentSection.id,
            DocumentSection.title,
            DocumentSection.content,
        ).where(DocumentSection.summary_embedding.is_(None))
        if attachment_id is not None:
            q = q.where(DocumentSection.attachment_id == attachment_id)

        rows = (await self.db.execute(q)).all()
        if not rows:
            return {"updated": 0}

        texts = [
            f"{r.title}\n\n{(r.content or '')[:2000]}" for r in rows
        ]
        embeddings = await self.embedding.embed_texts(texts)

        updated = 0
        for row, emb in zip(rows, embeddings):
            if emb is None:
                continue
            await self.db.execute(
                sa_update(DocumentSection)
                .where(DocumentSection.id == row.id)
                .values(summary_embedding=emb)
            )
            updated += 1

        await self.db.commit()
        return {"updated": updated}

    async def delete_document_chunks(self, attachment_id: int) -> int:
        result = await self.db.execute(
            delete(DocumentChunk)
            .where(DocumentChunk.attachment_id == attachment_id)
            .returning(DocumentChunk.id)
        )
        deleted = len(result.scalars().all())
        await self.db.execute(
            delete(DocumentSection).where(
                DocumentSection.attachment_id == attachment_id
            )
        )
        await self.db.execute(
            delete(DocumentSummary).where(
                DocumentSummary.attachment_id == attachment_id
            )
        )
        await self.db.commit()
        log(f"Deleted {deleted} chunks for attachment {attachment_id}")
        return deleted

    async def get_user_documents(self, user_id: int) -> list[dict]:
        result = await self.db.execute(
            select(Attachment)
            .where(
                and_(
                    Attachment.user_id == user_id,
                    Attachment.is_embedded == True,  # noqa: E712
                )
            )
            .order_by(Attachment.created_at.desc())
        )
        return [_attachment_to_dict(a) for a in result.scalars().all()]

    async def get_company_documents(self) -> list[dict]:
        result = await self.db.execute(
            select(Attachment)
            .where(
                and_(
                    Attachment.is_company_doc == True,  # noqa: E712
                    Attachment.is_embedded == True,  # noqa: E712
                )
            )
            .order_by(Attachment.created_at.desc())
        )
        return [_attachment_to_dict(a) for a in result.scalars().all()]

    async def _set_status(
        self, attachment: Attachment, status: str
    ) -> None:
        attachment.processing_status = status
        await self.db.commit()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _section_group_prefix(title: str) -> Optional[str]:
    """
    Return the "X.Y" parent group prefix for a section title.

    "2.1.1 Foo" -> "2.1"
    "2.1.2 Bar" -> "2.1"
    "2.1 Foo"   -> "2.1"  (the group header itself)
    "c) Foo"    -> None
    "3. Foo"    -> None   (top-level, no subgroup)
    """
    t = title.strip()
    m = re.match(r'^(\d+\.\d+)\.\d+', t)
    if m:
        return m.group(1)
    m = re.match(r'^(\d+\.\d+)[\s\.]', t)
    if m:
        return m.group(1)
    return None


def _is_group_header(title: str, prefix: str) -> bool:
    """True if this section IS the header for the given X.Y group.

    "2.1 Foo"   -> True   (space after prefix)
    "2.1.1 Foo" -> False  (dot means it's a child, not the group header)
    """
    return bool(re.match(rf'^{re.escape(prefix)}\s', title.strip()))


def _nearest_group_prefix(section_index: int, all_secs: list) -> Optional[str]:
    """
    Walk backwards from `section_index` and return the group prefix of the
    nearest numbered section above (e.g. "2.1" for "2.1.1 ...").

    Used for unnumbered sub-bullets so they inherit their parent's group.
    """
    for s in reversed(all_secs):
        if s.section_index >= section_index:
            continue
        prefix = _section_group_prefix(s.title)
        if prefix is not None:
            return prefix
    return None


def _is_sibling_or_higher(title: str, prefix: str) -> bool:
    """
    True if this title starts a section that is a sibling or ancestor
    of the given prefix — i.e., marks the end of the current group.

    prefix "2.1": "2.2 ...", "3. ..." -> True
                  "2.1.1 ..."         -> False (still inside the group)
    """
    t = title.strip()
    parts = prefix.split('.')
    parent, group_num = parts[0], int(parts[1])

    # Same parent, higher sibling: "2.2", "2.3", …
    m = re.match(rf'^{re.escape(parent)}\.(\d+)[\s\.]', t)
    if m and int(m.group(1)) > group_num:
        return True

    # Higher-level section: "3.", "4.", …
    m = re.match(r'^(\d+)[\.\s]', t)
    if m and int(m.group(1)) > int(parent):
        return True

    return False


def _build_heading_context(doc_title: str, sec: ParsedSection) -> str:
    """Build 'Doc Title > Section Title' breadcrumb string."""
    parts = [p for p in [doc_title, sec.title] if p]
    return " > ".join(parts)


def _chunk_section(content: str) -> list[str]:
    """
    Split section content into chunks (500–1000 tokens target).

    Rules:
    - Tables (markdown | … | lines) are never split.
    - Code fences are never split.
    - Otherwise split at paragraph / sentence boundaries.
    """
    if not content.strip():
        return []

    # Split into semantic blocks: tables/code-fences are atomic.
    blocks = _split_blocks(content)

    chunks: list[str] = []
    buffer = ""

    for block in blocks:
        combined = (buffer + "\n\n" + block).strip() if buffer else block
        if len(combined) <= _CHUNK_MAX_CHARS:
            buffer = combined
        else:
            # Flush current buffer
            if buffer:
                chunks.append(buffer.strip())
            # If the block itself exceeds max, split it on sentences
            if len(block) > _CHUNK_MAX_CHARS:
                chunks.extend(_split_text(block))
                buffer = ""
            else:
                buffer = block

    if buffer.strip():
        chunks.append(buffer.strip())

    return [c for c in chunks if c]


def _split_blocks(text: str) -> list[str]:
    """Split text into atomic blocks (tables, fences, paragraphs)."""
    blocks: list[str] = []
    lines = text.splitlines()
    current: list[str] = []
    in_table = False
    in_fence = False

    def flush_current() -> None:
        joined = "\n".join(current).strip()
        if joined:
            blocks.append(joined)
        current.clear()

    for line in lines:
        is_table_row = bool(re.match(r'^\s*\|', line))
        is_fence = line.startswith("```") or line.startswith("~~~")

        if is_fence:
            in_fence = not in_fence
            current.append(line)
            if not in_fence:
                flush_current()
        elif in_fence:
            current.append(line)
        elif is_table_row:
            if not in_table:
                flush_current()
                in_table = True
            current.append(line)
        else:
            if in_table:
                flush_current()
                in_table = False
            if not line.strip() and current:
                flush_current()
            elif line.strip():
                current.append(line)

    flush_current()
    return blocks


def _split_text(text: str) -> list[str]:
    """Split a long text at sentence boundaries with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_MAX_CHARS, len(text))
        if end < len(text):
            # Back up to last sentence end
            search = text[max(end - 200, start):end]
            for sep in ('. ', '? ', '! ', '\n\n', '\n'):
                pos = search.rfind(sep)
                if pos != -1:
                    end = max(end - 200, start) + pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - _CHUNK_OVERLAP_CHARS
        if start >= len(text):
            break
    return chunks


def _access_filter(user_id: Optional[int]):
    if user_id:
        return or_(
            DocumentChunk.is_company_doc == True,  # noqa: E712
            DocumentChunk.user_id == user_id,
        )
    return DocumentChunk.is_company_doc == True  # noqa: E712


def _attachment_access_filter(user_id: Optional[int]):
    if user_id:
        return or_(
            Attachment.is_company_doc == True,  # noqa: E712
            Attachment.user_id == user_id,
        )
    return Attachment.is_company_doc == True  # noqa: E712


def _bm25_rerank(
    query: str,
    rows: list,
    top_k: int,
) -> list:
    """Re-rank chunk rows using BM25 scores combined with vector distance."""
    try:
        from rank_bm25 import BM25Okapi

        tokens = query.lower().split()
        corpus = [
            (chunk.chunk_text or "").lower().split()
            for chunk, _, _ in rows
        ]
        bm25 = BM25Okapi(corpus)
        bm25_scores = bm25.get_scores(tokens)

        # Normalise BM25 to [0,1]
        max_bm25 = max(bm25_scores) if max(bm25_scores) > 0 else 1.0

        combined = []
        for i, (chunk, fname, dist) in enumerate(rows):
            vec_score = 1 - dist          # higher = better
            kw_score = bm25_scores[i] / max_bm25
            score = 0.8 * vec_score + 0.2 * kw_score
            combined.append((score, chunk, fname, dist))

        combined.sort(key=lambda x: x[0], reverse=True)
        return [(c, f, d) for _, c, f, d in combined[:top_k]]

    except ImportError:
        # rank_bm25 not installed — fall back to pure vector order
        return rows[:top_k]


def _attachment_to_dict(att: Attachment) -> dict:
    return {
        "id": att.id,
        "filename": att.original_filename,
        "content_type": att.content_type,
        "file_size": att.file_size,
        "is_company_doc": att.is_company_doc,
        "created_at": att.created_at.isoformat(),
        "graph_status": att.graph_status,
        "processing_status": att.processing_status,
        "sections_count": att.sections_count,
        "version": att.version,
        "folder_id": att.folder_id,
    }
