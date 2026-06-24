"""
Embedding service using Ollama for generating vector embeddings.
"""

import time
import httpx
from typing import Optional

from app.config import settings


def log(message: str) -> None:
    pass


class EmbeddingService:
    """Service for generating text embeddings using Ollama."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_EMBEDDING_MODEL
        self.timeout = 300.0

    async def embed_text(self, text: str) -> Optional[list[float]]:
        results = await self.embed_texts([text])
        return results[0]

    async def embed_texts(
        self, texts: list[str]
    ) -> list[Optional[list[float]]]:
        total = len(texts)
        log(f"Generating {total} embeddings using {self.model}...")
        start_time = time.time()

        # Ollama processes sequentially — keep requests short.
        # Timeout is generous: bge-m3 cold-start on Mac Mini ~2-3 min.
        _SUB_BATCH = 10
        _TIMEOUT = 300.0
        all_embeddings: list[Optional[list[float]]] = []

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                for i in range(0, total, _SUB_BATCH):
                    sub = texts[i: i + _SUB_BATCH]
                    t = time.time()
                    response = await client.post(
                        f"{self.base_url}/api/embed",
                        json={
                            "model": self.model,
                            "input": sub,
                            "keep_alive": -1,
                        },
                    )
                    response.raise_for_status()
                    batch_embs = response.json().get("embeddings", [])
                    while len(batch_embs) < len(sub):
                        batch_embs.append(None)
                    all_embeddings.extend(batch_embs)
                    log(
                        f"  [{i + len(sub)}/{total}] sub-batch"
                        f" in {time.time() - t:.2f}s"
                    )

            elapsed = time.time() - start_time
            success_count = sum(
                1 for e in all_embeddings if e is not None
            )
            log(
                f"✓ Generated {success_count}/{total} embeddings"
                f" in {elapsed:.2f}s"
            )
            return all_embeddings
        except Exception as e:
            log(f"✗ Embedding error: {e}")
            return [None] * total

    async def health_check(self) -> bool:
        """Check if the embedding model is available."""
        try:
            embedding = await self.embed_text("test")
            if embedding and len(embedding) == settings.RAG_EMBEDDING_DIM:
                return True
            got = len(embedding) if embedding else 0
            log(
                f"⚠ Embedding dimension mismatch: got {got},"
                f" expected {settings.RAG_EMBEDDING_DIM}"
            )
            return False
        except Exception as e:
            log(f"✗ Health check failed: {e}")
            return False
