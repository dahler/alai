"""
Embedding service using Ollama for generating vector embeddings.
"""

import time
import httpx
from typing import Optional

from app.config import settings


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [EMBEDDING] {message}")


class EmbeddingService:
    """Service for generating text embeddings using Ollama."""

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_EMBEDDING_MODEL
        self.timeout = 60.0

    async def embed_text(self, text: str) -> Optional[list[float]]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={
                        "model": self.model,
                        "prompt": text,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data.get("embedding")
        except Exception as e:
            log(f"✗ Embedding error: {e}")
            return None

    async def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (None for failed texts)
        """
        embeddings = []
        total = len(texts)

        log(f"Generating {total} embeddings using {self.model}...")
        start_time = time.time()

        for i, text in enumerate(texts):
            embedding = await self.embed_text(text)
            embeddings.append(embedding)

            # Log progress every 10 chunks
            if (i + 1) % 10 == 0 or i == total - 1:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log(f"  Progress: {i + 1}/{total} ({rate:.1f}/s)")

        elapsed = time.time() - start_time
        success_count = sum(1 for e in embeddings if e is not None)
        log(f"✓ Generated {success_count}/{total} embeddings in {elapsed:.2f}s")

        return embeddings

    async def health_check(self) -> bool:
        """Check if the embedding model is available."""
        try:
            # Try to generate a simple embedding
            embedding = await self.embed_text("test")
            if embedding and len(embedding) == settings.RAG_EMBEDDING_DIM:
                return True
            log(f"⚠ Embedding dimension mismatch: got {len(embedding) if embedding else 0}, expected {settings.RAG_EMBEDDING_DIM}")
            return False
        except Exception as e:
            log(f"✗ Health check failed: {e}")
            return False
