"""
Entity Extraction Service using Ollama.
Extracts named entities from text chunks for knowledge graph construction.
"""

import json
import re
import time
from typing import Optional
from dataclasses import dataclass
import httpx

from app.config import settings


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [ENTITY_EXTRACT] {message}")


# Supported entity types
ENTITY_TYPES = [
    "person",
    "organization",
    "company",
    "regulation",
    "product",
    "technology",
    "country",
    "location",
    "date",
    "project",
    "concept",
    "event",
    "document",
    "standard",
    "process",
]

# Entity extraction prompt - strict JSON output
# Note: Double curly braces {{ }} are used to escape them for Python .format()
ENTITY_EXTRACTION_PROMPT = """Extract named entities from the following text.

RULES:
1. Output ONLY valid JSON, no markdown, no explanation
2. Extract entities of these types: person, organization, company, regulation, product, technology, country, location, date, project, concept, event, document, standard, process
3. Normalize entity names (e.g., "Bank Indonesia" not "bank indonesia")
4. Include confidence score (0.0-1.0) for each entity
5. Do not include generic terms or pronouns

OUTPUT FORMAT:
{{
  "entities": [
    {{"name": "Entity Name", "type": "entity_type", "confidence": 0.95}}
  ]
}}

TEXT:
{text}

JSON:"""


@dataclass
class ExtractedEntity:
    """Represents an extracted entity."""
    name: str
    entity_type: str
    confidence: float = 1.0

    def normalize_name(self) -> str:
        """Return normalized version of entity name for matching."""
        # Lowercase, remove extra spaces, strip
        normalized = self.name.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
        # Remove common prefixes/suffixes
        for prefix in ['the ', 'a ', 'an ']:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        return normalized


class EntityExtractionService:
    """
    Service for extracting named entities from text using Ollama.
    Uses gemma3:4b by default for efficient CPU inference.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_TEXT_MODEL  # gemma3:4b
        self.timeout = 120.0  # Entity extraction can take time

    async def extract_entities(
        self,
        text: str,
        max_entities: int = 50,
    ) -> list[ExtractedEntity]:
        """
        Extract entities from text using LLM.

        Args:
            text: Text to extract entities from
            max_entities: Maximum number of entities to extract

        Returns:
            List of extracted entities
        """
        if not text or len(text.strip()) < 10:
            return []

        # Truncate very long texts
        if len(text) > 4000:
            text = text[:4000] + "..."

        prompt = ENTITY_EXTRACTION_PROMPT.format(text=text)

        try:
            log(f"Extracting entities from {len(text)} chars using {self.model}...")
            start_time = time.time()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,  # Low temp for deterministic output
                            "num_predict": 2000,
                            "top_p": 0.9,
                        }
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_output = data.get("response", "")

            elapsed = time.time() - start_time
            entities = self._parse_entities(raw_output, max_entities)
            log(f"Extracted {len(entities)} entities in {elapsed:.2f}s")

            return entities

        except Exception as e:
            log(f"Entity extraction error: {e}")
            return []

    def _parse_entities(
        self,
        raw_output: str,
        max_entities: int,
    ) -> list[ExtractedEntity]:
        """Parse LLM output to extract entities."""
        # Clean the output
        cleaned = raw_output.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(cleaned)
            return self._validate_entities(parsed, max_entities)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from text
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return self._validate_entities(parsed, max_entities)
            except json.JSONDecodeError:
                pass

        # Try to extract JSON array
        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            try:
                entities_list = json.loads(array_match.group())
                return self._validate_entities({"entities": entities_list}, max_entities)
            except json.JSONDecodeError:
                pass

        log(f"Failed to parse entity extraction output: {cleaned[:200]}...")
        return []

    def _validate_entities(
        self,
        parsed: dict,
        max_entities: int,
    ) -> list[ExtractedEntity]:
        """Validate and convert parsed JSON to ExtractedEntity objects."""
        entities = []
        raw_entities = parsed.get("entities", [])

        if not isinstance(raw_entities, list):
            return []

        for item in raw_entities[:max_entities]:
            if not isinstance(item, dict):
                continue

            name = item.get("name", "").strip()
            entity_type = item.get("type", "").lower().strip()
            confidence = item.get("confidence", 1.0)

            # Validate required fields
            if not name or len(name) < 2:
                continue

            # Validate entity type
            if entity_type not in ENTITY_TYPES:
                # Try to match similar type
                entity_type = self._match_entity_type(entity_type)
                if not entity_type:
                    entity_type = "concept"  # Default fallback

            # Validate confidence
            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.8

            entities.append(ExtractedEntity(
                name=name,
                entity_type=entity_type,
                confidence=confidence,
            ))

        return entities

    def _match_entity_type(self, entity_type: str) -> Optional[str]:
        """Try to match an invalid entity type to a valid one."""
        type_mappings = {
            "org": "organization",
            "corp": "company",
            "firm": "company",
            "enterprise": "company",
            "place": "location",
            "city": "location",
            "region": "location",
            "rule": "regulation",
            "law": "regulation",
            "policy": "regulation",
            "tech": "technology",
            "system": "technology",
            "tool": "technology",
            "software": "technology",
            "hardware": "technology",
            "nation": "country",
            "state": "country",
            "individual": "person",
            "human": "person",
            "term": "concept",
            "idea": "concept",
            "topic": "concept",
            "service": "product",
            "offering": "product",
        }

        # Check direct mapping
        if entity_type in type_mappings:
            return type_mappings[entity_type]

        # Check partial match
        for key, value in type_mappings.items():
            if key in entity_type or entity_type in key:
                return value

        return None

    async def extract_entities_batch(
        self,
        texts: list[str],
        max_entities_per_chunk: int = 20,
    ) -> list[list[ExtractedEntity]]:
        """
        Extract entities from multiple text chunks.

        Args:
            texts: List of text chunks
            max_entities_per_chunk: Max entities per chunk

        Returns:
            List of entity lists (one per chunk)
        """
        results = []
        total = len(texts)

        log(f"Batch extracting entities from {total} chunks...")
        start_time = time.time()

        for i, text in enumerate(texts):
            entities = await self.extract_entities(text, max_entities_per_chunk)
            results.append(entities)

            # Log progress every 5 chunks
            if (i + 1) % 5 == 0 or i == total - 1:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log(f"  Progress: {i + 1}/{total} ({rate:.2f}/s)")

        total_entities = sum(len(r) for r in results)
        elapsed = time.time() - start_time
        log(f"Batch extraction complete: {total_entities} entities in {elapsed:.2f}s")

        return results

    async def health_check(self) -> bool:
        """Check if the extraction model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_name = self.model.split(":")[0]
                    return any(m.get("name", "").startswith(model_name) for m in models)
        except Exception:
            pass
        return False
