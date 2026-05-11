"""
Relationship Extraction Service using Ollama.
Extracts relationships between entities for knowledge graph construction.
"""

import json
import re
import time
from typing import Optional
from dataclasses import dataclass
import httpx

from app.config import settings
from app.services.entity_extraction import ExtractedEntity


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [REL_EXTRACT] {message}")


# Supported relationship types
RELATIONSHIP_TYPES = [
    "regulates",
    "regulated_by",
    "owns",
    "owned_by",
    "modifies",
    "modified_by",
    "references",
    "referenced_by",
    "affects",
    "affected_by",
    "depends_on",
    "dependency_of",
    "belongs_to",
    "contains",
    "mentions",
    "mentioned_in",
    "collaborates_with",
    "competes_with",
    "partners_with",
    "subsidiary_of",
    "parent_of",
    "located_in",
    "works_for",
    "employs",
    "created_by",
    "creates",
    "uses",
    "used_by",
    "implements",
    "implemented_by",
    "provides",
    "provided_by",
    "related_to",
    "part_of",
    "has_part",
    "predecessor_of",
    "successor_of",
    "version_of",
]

# Relationship extraction prompt - strict JSON output
RELATIONSHIP_EXTRACTION_PROMPT = """Extract relationships between entities from the following text.

ENTITIES IN TEXT:
{entities}

RULES:
1. Output ONLY valid JSON, no markdown, no explanation
2. Only extract relationships between the provided entities
3. Use these relationship types: regulates, owns, modifies, references, affects, depends_on, belongs_to, mentions, collaborates_with, uses, implements, provides, related_to, part_of, created_by, works_for, located_in
4. Include confidence score (0.0-1.0) for each relationship
5. Include a brief context/evidence from the text

OUTPUT FORMAT:
{{
  "relationships": [
    {{
      "source": "Source Entity Name",
      "relation": "relationship_type",
      "target": "Target Entity Name",
      "confidence": 0.9,
      "context": "Brief evidence from text"
    }}
  ]
}}

TEXT:
{text}

JSON:"""


@dataclass
class ExtractedRelationship:
    """Represents an extracted relationship between entities."""
    source: str
    relation_type: str
    target: str
    confidence: float = 1.0
    context: Optional[str] = None

    def normalize_source(self) -> str:
        """Return normalized source entity name."""
        return self.source.lower().strip()

    def normalize_target(self) -> str:
        """Return normalized target entity name."""
        return self.target.lower().strip()


class RelationshipExtractionService:
    """
    Service for extracting relationships between entities using Ollama.
    Uses gemma3:4b by default for efficient CPU inference.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_TEXT_MODEL  # gemma3:4b
        self.timeout = 120.0

    async def extract_relationships(
        self,
        text: str,
        entities: list[ExtractedEntity],
        max_relationships: int = 30,
    ) -> list[ExtractedRelationship]:
        """
        Extract relationships between entities from text.

        Args:
            text: Text containing the entities
            entities: List of entities to find relationships between
            max_relationships: Maximum number of relationships to extract

        Returns:
            List of extracted relationships
        """
        if not text or not entities or len(entities) < 2:
            return []

        # Truncate very long texts
        if len(text) > 4000:
            text = text[:4000] + "..."

        # Format entities for prompt
        entity_list = "\n".join(
            f"- {e.name} ({e.entity_type})"
            for e in entities[:30]  # Limit entities in prompt
        )

        prompt = RELATIONSHIP_EXTRACTION_PROMPT.format(
            entities=entity_list,
            text=text,
        )

        try:
            log(f"Extracting relationships from {len(entities)} entities...")
            start_time = time.time()

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 2000,
                            "top_p": 0.9,
                        }
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_output = data.get("response", "")

            elapsed = time.time() - start_time
            relationships = self._parse_relationships(
                raw_output, entities, max_relationships
            )
            log(f"Extracted {len(relationships)} relationships in {elapsed:.2f}s")

            return relationships

        except Exception as e:
            log(f"Relationship extraction error: {e}")
            return []

    def _parse_relationships(
        self,
        raw_output: str,
        entities: list[ExtractedEntity],
        max_relationships: int,
    ) -> list[ExtractedRelationship]:
        """Parse LLM output to extract relationships."""
        # Build entity name lookup for validation
        entity_names = {e.name.lower().strip() for e in entities}
        entity_names.update(e.normalize_name() for e in entities)

        # Clean the output
        cleaned = raw_output.strip()

        # Try direct JSON parse
        try:
            parsed = json.loads(cleaned)
            return self._validate_relationships(
                parsed, entity_names, max_relationships
            )
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from text
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return self._validate_relationships(
                    parsed, entity_names, max_relationships
                )
            except json.JSONDecodeError:
                pass

        # Try to extract JSON array
        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            try:
                rels_list = json.loads(array_match.group())
                return self._validate_relationships(
                    {"relationships": rels_list}, entity_names, max_relationships
                )
            except json.JSONDecodeError:
                pass

        log(f"Failed to parse relationship extraction output: {cleaned[:200]}...")
        return []

    def _validate_relationships(
        self,
        parsed: dict,
        entity_names: set[str],
        max_relationships: int,
    ) -> list[ExtractedRelationship]:
        """Validate and convert parsed JSON to ExtractedRelationship objects."""
        relationships = []
        raw_relationships = parsed.get("relationships", [])

        if not isinstance(raw_relationships, list):
            return []

        for item in raw_relationships[:max_relationships]:
            if not isinstance(item, dict):
                continue

            source = item.get("source", "").strip()
            relation = item.get("relation", "").lower().strip()
            target = item.get("target", "").strip()
            confidence = item.get("confidence", 1.0)
            context = item.get("context", "")

            # Validate required fields
            if not source or not target or not relation:
                continue

            # Validate source and target exist in entities
            source_lower = source.lower().strip()
            target_lower = target.lower().strip()

            source_valid = any(
                source_lower in name or name in source_lower
                for name in entity_names
            )
            target_valid = any(
                target_lower in name or name in target_lower
                for name in entity_names
            )

            if not (source_valid and target_valid):
                continue

            # Validate/normalize relationship type
            relation = self._normalize_relation_type(relation)
            if not relation:
                relation = "related_to"  # Default fallback

            # Validate confidence
            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.8

            # Truncate context
            if context and len(context) > 500:
                context = context[:500] + "..."

            relationships.append(ExtractedRelationship(
                source=source,
                relation_type=relation,
                target=target,
                confidence=confidence,
                context=context if context else None,
            ))

        return relationships

    def _normalize_relation_type(self, relation: str) -> Optional[str]:
        """Normalize a relationship type to a standard form."""
        # Direct match
        if relation in RELATIONSHIP_TYPES:
            return relation

        # Common mappings
        relation_mappings = {
            "regulate": "regulates",
            "own": "owns",
            "modify": "modifies",
            "reference": "references",
            "affect": "affects",
            "depend": "depends_on",
            "depend_on": "depends_on",
            "belong": "belongs_to",
            "belong_to": "belongs_to",
            "mention": "mentions",
            "collaborate": "collaborates_with",
            "compete": "competes_with",
            "partner": "partners_with",
            "work": "works_for",
            "work_for": "works_for",
            "employ": "employs",
            "create": "creates",
            "use": "uses",
            "implement": "implements",
            "provide": "provides",
            "relate": "related_to",
            "relate_to": "related_to",
            "part": "part_of",
            "contain": "contains",
            "include": "contains",
            "has": "contains",
            "is_part_of": "part_of",
            "is_a": "related_to",
            "type_of": "related_to",
            "instance_of": "related_to",
        }

        # Check mapping
        if relation in relation_mappings:
            return relation_mappings[relation]

        # Check partial match
        for key, value in relation_mappings.items():
            if key in relation:
                return value

        # Check if it's close to a valid type
        for valid_type in RELATIONSHIP_TYPES:
            if valid_type.startswith(relation[:4]) or relation.startswith(valid_type[:4]):
                return valid_type

        return None

    async def extract_relationships_batch(
        self,
        chunks_with_entities: list[tuple[str, list[ExtractedEntity]]],
        max_relationships_per_chunk: int = 15,
    ) -> list[list[ExtractedRelationship]]:
        """
        Extract relationships from multiple chunks with their entities.

        Args:
            chunks_with_entities: List of (text, entities) tuples
            max_relationships_per_chunk: Max relationships per chunk

        Returns:
            List of relationship lists (one per chunk)
        """
        results = []
        total = len(chunks_with_entities)

        log(f"Batch extracting relationships from {total} chunks...")
        start_time = time.time()

        for i, (text, entities) in enumerate(chunks_with_entities):
            relationships = await self.extract_relationships(
                text, entities, max_relationships_per_chunk
            )
            results.append(relationships)

            # Log progress every 5 chunks
            if (i + 1) % 5 == 0 or i == total - 1:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log(f"  Progress: {i + 1}/{total} ({rate:.2f}/s)")

        total_rels = sum(len(r) for r in results)
        elapsed = time.time() - start_time
        log(f"Batch extraction complete: {total_rels} relationships in {elapsed:.2f}s")

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
