"""
Knowledge Graph API router.
Endpoints for graph operations, hybrid search, and entity management.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel, Field
from typing import Optional, List

from app.database import get_db
from app.middleware.auth import get_current_user, get_optional_user
from app.models.user import User
from app.models.attachment import Attachment
from app.services.knowledge_graph import KnowledgeGraphService, extract_graph_background


router = APIRouter(prefix="/graph", tags=["knowledge-graph"])


# Request/Response Models

class HybridSearchRequest(BaseModel):
    """Request body for hybrid search."""
    query: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    vector_weight: float = Field(default=0.6, ge=0, le=1)
    graph_weight: float = Field(default=0.4, ge=0, le=1)


class SearchResultItem(BaseModel):
    """Single search result."""
    chunk_id: int
    chunk_text: str
    document_id: int
    filename: str
    vector_score: float
    graph_score: float
    combined_score: float
    matched_entities: List[dict]
    relationships: List[dict]
    source: str


class HybridSearchResponse(BaseModel):
    """Response from hybrid search."""
    query: str
    results: List[SearchResultItem]
    count: int


class EntitySearchResponse(BaseModel):
    """Response from entity search."""
    query: str
    results: List[dict]
    count: int


class GraphStatsResponse(BaseModel):
    """Response with graph statistics."""
    total_entities: int
    total_relationships: int
    documents_with_graph: int
    entities_by_type: dict
    relationships_by_type: dict


class IngestDocumentRequest(BaseModel):
    """Request to ingest a document with graph extraction."""
    attachment_id: int
    is_company_doc: bool = False
    extract_graph: bool = True


class IngestDocumentResponse(BaseModel):
    """Response from document ingestion."""
    attachment_id: int
    chunks_created: int
    entities_extracted: int
    entities_new: int
    entities_linked: int
    relationships_extracted: int
    relationships_created: int
    processing_time: float


# Endpoints

@router.post("/search", response_model=HybridSearchResponse)
async def hybrid_search(
    request: HybridSearchRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Perform hybrid search combining vector similarity and knowledge graph.

    This endpoint:
    1. Searches using semantic vector similarity
    2. Extracts entities from the query
    3. Traverses the knowledge graph
    4. Merges and ranks results
    """
    kg_service = KnowledgeGraphService(db)

    results = await kg_service.hybrid_search(
        query=request.query,
        user_id=user.id if user else None,
        top_k=request.top_k,
        vector_weight=request.vector_weight,
        graph_weight=request.graph_weight,
    )

    return HybridSearchResponse(
        query=request.query,
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                chunk_text=r.chunk_text,
                document_id=r.document_id,
                filename=r.filename,
                vector_score=r.vector_score,
                graph_score=r.graph_score,
                combined_score=r.combined_score,
                matched_entities=r.matched_entities,
                relationships=r.relationships,
                source=r.source,
            )
            for r in results
        ],
        count=len(results),
    )


@router.post("/ingest", response_model=IngestDocumentResponse)
async def ingest_document(
    request: IngestDocumentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a document into both vector store and knowledge graph.

    This endpoint:
    1. Extracts text from document
    2. Chunks and embeds text
    3. Extracts entities
    4. Extracts relationships
    5. Links to existing knowledge graph
    """
    # Check admin permission for company docs
    if request.is_company_doc and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create company documents",
        )

    kg_service = KnowledgeGraphService(db)

    stats = await kg_service.ingest_document(
        attachment_id=request.attachment_id,
        user_id=user.id,
        is_company_doc=request.is_company_doc,
        extract_graph=request.extract_graph,
    )

    if "error" in stats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=stats["error"],
        )

    return IngestDocumentResponse(**stats)


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph statistics."""
    kg_service = KnowledgeGraphService(db)
    stats = await kg_service.get_graph_stats()
    return GraphStatsResponse(**stats)


@router.get("/overview")
async def get_graph_overview(
    limit: int = Query(default=100, ge=10, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Return top N entities by mention count + all relationships between them."""
    from app.models.entity import Entity
    from app.models.relationship import EntityRelationship

    result = await db.execute(
        select(Entity).order_by(Entity.mention_count.desc()).limit(limit)
    )
    entities = result.scalars().all()
    entity_ids = {e.id for e in entities}

    rels_result = await db.execute(
        select(EntityRelationship).where(
            EntityRelationship.source_entity_id.in_(entity_ids),
            EntityRelationship.target_entity_id.in_(entity_ids),
        )
    )
    relationships = rels_result.scalars().all()

    return {
        "nodes": [
            {
                "id": e.id,
                "name": e.name,
                "type": e.entity_type,
                "mention_count": e.mention_count,
            }
            for e in entities
        ],
        "edges": [
            {
                "source_id": r.source_entity_id,
                "relation": r.relation_type,
                "target_id": r.target_entity_id,
                "confidence": r.confidence,
            }
            for r in relationships
        ],
    }


@router.get("/entities/search", response_model=EntitySearchResponse)
async def search_entities(
    query: str = Query(..., min_length=1),
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search for entities by name or type."""
    kg_service = KnowledgeGraphService(db)

    results = await kg_service.search_entities(
        query=query,
        entity_type=entity_type,
        limit=limit,
    )

    return EntitySearchResponse(
        query=query,
        results=results,
        count=len(results),
    )


@router.get("/entities/{entity_id}")
async def get_entity_details(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about an entity."""
    kg_service = KnowledgeGraphService(db)

    entity = await kg_service.get_entity_details(entity_id)

    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found",
        )

    return entity


@router.get("/documents/{document_id}")
async def get_document_graph(
    document_id: int,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph data for a specific document."""
    kg_service = KnowledgeGraphService(db)

    graph = await kg_service.get_document_graph(document_id)

    return graph


@router.delete("/documents/{document_id}")
async def delete_document_graph(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete knowledge graph data for a document."""
    kg_service = KnowledgeGraphService(db)

    result = await kg_service.delete_document_graph(document_id)

    return {
        "message": "Document graph data deleted",
        **result,
    }


@router.get("/entities/{entity_id}/connections")
async def get_entity_connections(
    entity_id: int,
    max_depth: int = Query(default=2, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all connections for an entity through graph traversal.

    Returns entities and relationships up to max_depth hops away.
    """
    from app.services.graph_linking import GraphLinkingService

    linking_service = GraphLinkingService(db)
    connections = await linking_service.get_entity_connections(
        entity_id=entity_id,
        max_depth=max_depth,
    )

    return connections


@router.get("/entities/{entity_id}/documents")
async def get_entity_documents(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all documents that mention an entity."""
    from app.services.graph_linking import GraphLinkingService

    linking_service = GraphLinkingService(db)
    documents = await linking_service.get_documents_for_entity(entity_id)

    return {
        "entity_id": entity_id,
        "documents": documents,
        "count": len(documents),
    }


@router.get("/documents/{document_id}/related")
async def get_related_documents(
    document_id: int,
    min_shared_entities: int = Query(default=2, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    """
    Find documents related to a given document through shared entities.
    """
    from app.services.graph_linking import GraphLinkingService

    linking_service = GraphLinkingService(db)
    related = await linking_service.find_related_documents(
        document_id=document_id,
        min_shared_entities=min_shared_entities,
    )

    return {
        "document_id": document_id,
        "related_documents": related,
        "count": len(related),
    }


@router.post("/reextract-all")
async def reextract_all_graphs(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue knowledge graph extraction for all eligible embedded documents.

    Admins process all embedded documents.
    Regular users process only their own non-company documents.
    """
    conditions = [Attachment.is_embedded.is_(True)]
    if not user.is_admin:
        conditions.append(Attachment.user_id == user.id)
        conditions.append(Attachment.is_company_doc.is_(False))

    result = await db.execute(select(Attachment).where(*conditions))
    attachments = result.scalars().all()

    count = 0
    for attachment in attachments:
        attachment.graph_status = "pending"
        background_tasks.add_task(extract_graph_background, attachment.id)
        count += 1

    await db.commit()
    return {"queued": count}


class CompareSearchRequest(BaseModel):
    """Request for comparing search with and without graph expansion."""
    query: str = Field(..., min_length=3, max_length=500)
    top_k: int = Field(default=6, ge=1, le=20)


@router.post("/compare-search")
async def compare_search(
    request: CompareSearchRequest,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the same query with and without graph expansion, return both."""
    from app.services.rag import RAGService
    from app.models.entity import Entity
    from app.models.document_entity import DocumentEntity
    from app.models.relationship import EntityRelationship

    rag = RAGService(db)
    uid = user.id if user else None
    q = request.query
    k = request.top_k

    # ── Without graph: plain RAGService ──────────────────────────────────────
    plain = await rag.search(query=q, user_id=uid, top_k=k)

    # ── Graph: fast keyword entity match + 1-hop expansion ───────────────────
    words = [
        w.strip(".,;:()[]\"'")
        for w in q.lower().split()
        if len(w.strip(".,;:()[]\"'")) > 3
    ]
    entity_ids: set[int] = set()
    if words:
        conds = [Entity.normalized_name.ilike(f"%{w}%") for w in words[:10]]
        res = await db.execute(
            select(Entity.id).where(or_(*conds)).limit(30)
        )
        entity_ids = {row[0] for row in res.all()}

    if entity_ids:
        rel_res = await db.execute(
            select(
                EntityRelationship.source_entity_id,
                EntityRelationship.target_entity_id,
            ).where(
                or_(
                    EntityRelationship.source_entity_id.in_(entity_ids),
                    EntityRelationship.target_entity_id.in_(entity_ids),
                )
            ).limit(100)
        )
        for src, tgt in rel_res.all():
            entity_ids.add(src)
            entity_ids.add(tgt)

    graph_doc_ids: set[int] = set()
    if entity_ids:
        doc_res = await db.execute(
            select(DocumentEntity.document_id)
            .where(DocumentEntity.entity_id.in_(entity_ids))
            .distinct()
        )
        graph_doc_ids = {row[0] for row in doc_res.all()}

    # ── Fuse plain + graph-scoped via RRF ────────────────────────────────────
    if graph_doc_ids:
        graph_scoped = await rag.search(
            query=q,
            user_id=uid,
            top_k=k,
            document_ids=list(graph_doc_ids),
        )
        scores: dict[int, float] = {}
        by_id: dict[int, dict] = {}
        for rank, r in enumerate(plain):
            cid = r["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (61 + rank)
            by_id[cid] = r
        for rank, r in enumerate(graph_scoped):
            cid = r["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (61 + rank)
            if cid not in by_id:
                by_id[cid] = r
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        with_graph = [by_id[cid] for cid in sorted_ids[:k]]
    else:
        with_graph = plain

    def fmt(results: list[dict], graph_ids: set[int]) -> list[dict]:
        return [
            {
                "rank": i + 1,
                "filename": r["filename"],
                "similarity": round(r.get("similarity", 0), 3),
                "heading": r.get("heading_context") or "",
                "from_graph_doc": r.get("attachment_id") in graph_ids,
                "chunk_preview": (r.get("chunk_text") or "")[:300],
            }
            for i, r in enumerate(results)
        ]

    return {
        "query": q,
        "graph_entities_matched": len(entity_ids),
        "graph_docs_expanded": len(graph_doc_ids),
        "without_graph": fmt(plain, set()),
        "with_graph": fmt(with_graph, graph_doc_ids),
    }


@router.get("/health")
async def graph_health(
    db: AsyncSession = Depends(get_db),
):
    """Check knowledge graph service health."""
    from app.services.entity_extraction import EntityExtractionService
    from app.services.embedding import EmbeddingService

    entity_service = EntityExtractionService()
    embedding_service = EmbeddingService()

    entity_model_ok = await entity_service.health_check()
    embedding_model_ok = await embedding_service.health_check()

    kg_service = KnowledgeGraphService(db)
    stats = await kg_service.get_graph_stats()

    return {
        "status": "healthy" if entity_model_ok and embedding_model_ok else "degraded",
        "entity_extraction_model": "available" if entity_model_ok else "unavailable",
        "embedding_model": "available" if embedding_model_ok else "unavailable",
        "graph_stats": {
            "entities": stats["total_entities"],
            "relationships": stats["total_relationships"],
            "documents": stats["documents_with_graph"],
        },
    }
