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


# 6 focused entity types for Indonesian corporate knowledge base
ENTITY_TYPES = [
    "role",      # Jabatan, posisi, unit organisasi dengan wewenang/tanggung jawab
    "policy",    # Kebijakan, SOP, peraturan, ketentuan tertulis
    "process",   # Alur kerja atau prosedur multi-tahap
    "activity",  # Tindakan atau kegiatan tunggal yang spesifik
    "time",      # Batas waktu, durasi, frekuensi
    "report",    # Laporan, formulir, dokumen output
]

ENTITY_EXTRACTION_PROMPT = """Extract named entities from the following text from an Indonesian corporate document (policies, SOPs, procedures, regulations).

RULES:
1. Output ONLY valid JSON, no markdown, no explanation
2. Extract entities of ONLY these 6 types:
   - role: Jabatan, posisi, atau unit organisasi (e.g. "Direktur Keuangan", "Tim Procurement", "Komite Audit")
   - policy: Kebijakan, SOP, peraturan, atau ketentuan tertulis (e.g. "SOP Pengadaan Barang", "SE No. 5/2024")
   - process: Alur kerja atau prosedur yang memiliki beberapa tahapan (e.g. "prosedur approval", "alur pengajuan cuti")
   - activity: Tindakan atau kegiatan tunggal yang spesifik (e.g. "verifikasi dokumen", "menandatangani kontrak")
   - time: Batas waktu, durasi, atau frekuensi (e.g. "3 hari kerja", "paling lambat H+7", "setiap triwulan")
   - report: Laporan, formulir, atau dokumen output (e.g. "Laporan Keuangan Bulanan", "Berita Acara", "Formulir F-HR-001")
3. Do NOT extract: personal names, company names, locations, products, technology terms, or generic words
4. Normalize entity names properly (e.g. title case for roles)
5. Include confidence score (0.0-1.0) for each entity
6. Extract at most 15 entities

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
        normalized = self.name.lower().strip()
        normalized = re.sub(r'\s+', ' ', normalized)
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
        self.model = model or settings.OLLAMA_TEXT_MODEL
        self.timeout = 120.0

    async def extract_entities(
        self,
        text: str,
        max_entities: int = 15,
        document_title: Optional[str] = None,
    ) -> list[ExtractedEntity]:
        """Extract entities from text using LLM."""
        if not text or len(text.strip()) < 10:
            return []

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
        cleaned = raw_output.strip()

        try:
            parsed = json.loads(cleaned)
            return self._validate_entities(parsed, max_entities)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return self._validate_entities(parsed, max_entities)
            except json.JSONDecodeError:
                pass

        array_match = re.search(r'\[[\s\S]*\]', cleaned)
        if array_match:
            try:
                entities_list = json.loads(array_match.group())
                return self._validate_entities(
                    {"entities": entities_list}, max_entities
                )
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

            if not name or len(name) < 2:
                continue

            if entity_type not in ENTITY_TYPES:
                entity_type = self._match_entity_type(entity_type)
                if not entity_type:
                    continue  # Drop unknown types rather than guess

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
        """Map common synonyms to the 6 valid entity types."""
        type_mappings = {
            # role
            "jabatan": "role",
            "posisi": "role",
            "unit": "role",
            "department": "role",
            "divisi": "role",
            "bagian": "role",
            "tim": "role",
            "person": "role",
            "organization": "role",
            # policy
            "sop": "policy",
            "kebijakan": "policy",
            "peraturan": "policy",
            "regulation": "policy",
            "standard": "policy",
            "ketentuan": "policy",
            "document": "policy",
            # process
            "prosedur": "process",
            "alur": "process",
            "procedure": "process",
            "workflow": "process",
            # activity
            "kegiatan": "activity",
            "tindakan": "activity",
            "langkah": "activity",
            "action": "activity",
            "task": "activity",
            "event": "activity",
            # time
            "deadline": "time",
            "durasi": "time",
            "date": "time",
            "waktu": "time",
            "batas": "time",
            # report
            "laporan": "report",
            "formulir": "report",
            "form": "report",
            "dokumen": "report",
            "output": "report",
        }

        if entity_type in type_mappings:
            return type_mappings[entity_type]

        for key, value in type_mappings.items():
            if key in entity_type or entity_type in key:
                return value

        return None

    async def extract_entities_batch(
        self,
        texts: list[str],
        max_entities_per_chunk: int = 15,
    ) -> list[list[ExtractedEntity]]:
        """Extract entities from multiple text chunks."""
        results = []
        total = len(texts)

        log(f"Batch extracting entities from {total} chunks...")
        start_time = time.time()

        for i, text in enumerate(texts):
            entities = await self.extract_entities(text, max_entities_per_chunk)
            results.append(entities)

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
                    return any(
                        m.get("name", "").startswith(model_name)
                        for m in models
                    )
        except Exception:
            pass
        return False
