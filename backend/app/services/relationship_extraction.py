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


# Focused relationship types matching the 6 corporate entity types
RELATIONSHIP_TYPES = [
    "approves",          # ROLE → PROCESS/ACTIVITY
    "responsible_for",   # ROLE → PROCESS/ACTIVITY/REPORT
    "submits",           # ROLE → REPORT
    "receives",          # ROLE → REPORT
    "governs",           # POLICY → PROCESS/ROLE/ACTIVITY
    "produces",          # PROCESS/ACTIVITY → REPORT
    "part_of",           # ACTIVITY → PROCESS, PROCESS → PROCESS
    "follows",           # PROCESS → PROCESS (sequential step)
    "requires",          # PROCESS/POLICY → ACTIVITY/REPORT
    "due_within",        # PROCESS/REPORT/ACTIVITY → TIME
    "applies_to",        # TIME/POLICY → PROCESS/ROLE
    "references",        # POLICY → POLICY (cross-reference)
]

RELATIONSHIP_EXTRACTION_PROMPT = """Extract relationships between the listed entities from the following Indonesian corporate document text.

ENTITIES IN TEXT:
{entities}

RULES:
1. Output ONLY valid JSON, no markdown, no explanation
2. Only extract relationships between the provided entities
3. Use ONLY these relationship types:
   - approves: a role approves a process or activity
   - responsible_for: a role is responsible for a process, activity, or report
   - submits: a role submits/menyerahkan a report
   - receives: a role receives a report
   - governs: a policy governs/mengatur a process, role, or activity
   - produces: a process or activity produces a report
   - part_of: an activity is part of a process, or a process is part of another
   - follows: a process or activity follows another (sequential order)
   - requires: a process or policy requires an activity or report
   - due_within: a process, activity, or report must be done within a time period
   - applies_to: a time constraint or policy applies to a process or role
   - references: a policy references another policy
4. Include confidence score (0.0-1.0) for each relationship
5. Include a brief context/evidence from the text (max 200 chars)
6. Extract at most 10 relationships

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
        return self.source.lower().strip()

    def normalize_target(self) -> str:
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
        self.model = model or settings.OLLAMA_TEXT_MODEL
        self.timeout = 120.0

    async def extract_relationships(
        self,
        text: str,
        entities: list[ExtractedEntity],
        max_relationships: int = 10,
    ) -> list[ExtractedRelationship]:
        """Extract relationships between entities from text."""
        if not text or not entities or len(entities) < 2:
            return []

        if len(text) > 4000:
            text = text[:4000] + "..."

        entity_list = "\n".join(
            f"- {e.name} ({e.entity_type})"
            for e in entities[:20]
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
                            "num_predict": 1500,
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
            log(
                f"Extracted {len(relationships)} relationships "
                f"in {elapsed:.2f}s"
            )
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
        entity_names = {e.name.lower().strip() for e in entities}
        entity_names.update(e.normalize_name() for e in entities)

        cleaned = raw_output.strip()

        try:
            parsed = json.loads(cleaned)
            return self._validate_relationships(
                parsed, entity_names, max_relationships
            )
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return self._validate_relationships(
                    parsed, entity_names, max_relationships
                )
            except json.JSONDecodeError:
                pass

        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            try:
                rels_list = json.loads(array_match.group())
                return self._validate_relationships(
                    {"relationships": rels_list},
                    entity_names,
                    max_relationships,
                )
            except json.JSONDecodeError:
                pass

        log(
            f"Failed to parse relationship output: {cleaned[:200]}..."
        )
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

            if not source or not target or not relation:
                continue

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

            relation = self._normalize_relation_type(relation)
            if not relation:
                relation = "references"

            try:
                confidence = float(confidence)
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.8

            if context and len(context) > 300:
                context = context[:300] + "..."

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
        if relation in RELATIONSHIP_TYPES:
            return relation

        relation_mappings = {
            # English
            "approve": "approves",
            "responsible": "responsible_for",
            "submit": "submits",
            "receive": "receives",
            "govern": "governs",
            "regulate": "governs",
            "produce": "produces",
            "generate": "produces",
            "create": "produces",
            "belong": "part_of",
            "belong_to": "part_of",
            "is_part_of": "part_of",
            "follow": "follows",
            "succeed": "follows",
            "require": "requires",
            "need": "requires",
            "due": "due_within",
            "apply": "applies_to",
            "reference": "references",
            "cite": "references",
            # Indonesian
            "menyetujui": "approves",
            "menyetujui_proses": "approves",
            "bertanggung_jawab": "responsible_for",
            "bertanggung jawab": "responsible_for",
            "menyerahkan": "submits",
            "mengajukan": "submits",
            "menerima": "receives",
            "mengatur": "governs",
            "meregulasi": "governs",
            "menghasilkan": "produces",
            "membuat": "produces",
            "bagian_dari": "part_of",
            "bagian dari": "part_of",
            "mengikuti": "follows",
            "memerlukan": "requires",
            "membutuhkan": "requires",
            "dalam_waktu": "due_within",
            "berlaku_untuk": "applies_to",
            "berlaku untuk": "applies_to",
            "merujuk": "references",
            "mengacu": "references",
        }

        if relation in relation_mappings:
            return relation_mappings[relation]

        for key, value in relation_mappings.items():
            if key in relation or relation in key:
                return value

        for valid_type in RELATIONSHIP_TYPES:
            if (
                valid_type.startswith(relation[:5])
                or relation.startswith(valid_type[:5])
            ):
                return valid_type

        return None

    async def extract_relationships_batch(
        self,
        chunks_with_entities: list[tuple[str, list[ExtractedEntity]]],
        max_relationships_per_chunk: int = 10,
    ) -> list[list[ExtractedRelationship]]:
        """Extract relationships from multiple chunks with their entities."""
        results = []
        total = len(chunks_with_entities)

        log(f"Batch extracting relationships from {total} chunks...")
        start_time = time.time()

        for i, (text, entities) in enumerate(chunks_with_entities):
            relationships = await self.extract_relationships(
                text, entities, max_relationships_per_chunk
            )
            results.append(relationships)

            if (i + 1) % 5 == 0 or i == total - 1:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                log(f"  Progress: {i + 1}/{total} ({rate:.2f}/s)")

        total_rels = sum(len(r) for r in results)
        elapsed = time.time() - start_time
        log(
            f"Batch extraction complete: {total_rels} relationships "
            f"in {elapsed:.2f}s"
        )
        return results

    async def health_check(self) -> bool:
        """Check if the extraction model is available."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    model_name = self.model.split(":")[0]
                    return any(
                        m.get("name", "").startswith(model_name)
                        for m in models
                    )
        except Exception:
            pass
        return False
