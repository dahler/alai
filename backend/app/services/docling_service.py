"""
Docling-based document parsing service.

Sends documents to the remote Docling server (Mac Mini) for structured
parsing. Falls back to local PyMuPDF extraction if the remote server is
unavailable or not configured.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [DOCLING] {message}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParsedSection:
    """A heading + its content extracted from a document."""
    title: str
    level: int
    content: str
    page_start: int = 0
    page_end: int = 0
    section_index: int = 0
    subsections: list = field(default_factory=list)


@dataclass
class ParsedDocument:
    """Fully parsed document with structural hierarchy."""
    title: str
    sections: list
    full_markdown: str
    page_count: int
    file_type: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Supported types
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: set[str] = {
    '.pdf', '.docx', '.pptx', '.xlsx',
    '.html', '.htm', '.eml', '.msg',
    '.txt', '.md', '.markdown',
}

MIME_TO_EXT: dict[str, str] = {
    'application/pdf': '.pdf',
    'application/vnd.openxmlformats-officedocument'
    '.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument'
    '.presentationml.presentation': '.pptx',
    'application/vnd.openxmlformats-officedocument'
    '.spreadsheetml.sheet': '.xlsx',
    'text/html': '.html',
    'message/rfc822': '.eml',
    'application/vnd.ms-outlook': '.msg',
    'text/plain': '.txt',
    'text/markdown': '.md',
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class DoclingService:
    """
    Document parser that delegates to the remote Docling server (Mac Mini).

    Pipeline:
      1. If DOCLING_SERVER_URL is set → POST file to Mac Mini
      2. If Mac Mini fails or URL not set → PyMuPDF plain-text fallback

    No local subprocess is ever spawned.
    """

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse(
        self, file_path: str, original_name: str = ""
    ) -> Optional[ParsedDocument]:
        path = Path(file_path)
        if not path.exists():
            log(f"X File not found: {file_path}")
            return None

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            log(f"X Unsupported extension: {ext}")
            return None

        fallback_title = Path(original_name or path.name).stem
        log(f"Parsing {original_name or path.name}")
        t0 = time.time()

        from app.config import settings
        remote_url = settings.DOCLING_SERVER_URL.strip()

        if remote_url:
            log(f">> PATH: Docling server ({remote_url})")
            try:
                doc = await self._parse_remote(
                    path, fallback_title, remote_url
                )
                if doc:
                    log(
                        f"OK Remote: {len(doc.sections)} sections "
                        f"in {time.time() - t0:.2f}s"
                    )
                    return doc
                log("WARN Remote returned empty — falling back to PyMuPDF")
            except Exception as exc:
                log(f"WARN Remote error ({exc}) — falling back to PyMuPDF")
        else:
            log("WARN DOCLING_SERVER_URL not set — using PyMuPDF fallback")

        log(">> PATH: PyMuPDF local fallback")
        doc = await self._parse_fallback(path, fallback_title)
        if doc:
            log(
                f"OK PyMuPDF fallback: {len(doc.sections)} sections "
                f"in {time.time() - t0:.2f}s"
            )
        return doc

    async def parse_batch(
        self, items: list[tuple[str, str]]
    ) -> list[Optional[ParsedDocument]]:
        """
        Parse multiple documents via the remote Docling server in one request.
        Falls back to per-file PyMuPDF extraction if the remote call fails.

        items: list of (file_path, original_name)
        """
        if not items:
            return []

        from app.config import settings
        remote_url = settings.DOCLING_SERVER_URL.strip()

        names = [original_name or Path(fp).name for fp, original_name in items]
        log(f"Batch parsing {len(items)} file(s): {', '.join(names)}")

        if remote_url:
            log(f">> PATH: Docling server ({remote_url})")
            try:
                results = await self._parse_remote_batch(items, remote_url)
                ok = sum(1 for r in results if r is not None)
                log(f"OK Remote batch: {ok}/{len(items)} parsed")
                return results
            except Exception as exc:
                log(
                    f"WARN Remote batch error ({exc}) "
                    "— falling back to PyMuPDF"
                )
        else:
            log("WARN DOCLING_SERVER_URL not set — using PyMuPDF fallback")

        # PyMuPDF fallback for each file individually
        log(">> PATH: PyMuPDF local fallback")
        results = []
        for file_path, original_name in items:
            p = Path(file_path)
            fb = Path(original_name or p.name).stem
            results.append(await self._parse_fallback(p, fb))
        return results

    def is_supported(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS

    # ------------------------------------------------------------------
    # Remote Mac Mini
    # ------------------------------------------------------------------

    async def _parse_remote(
        self, path: Path, fallback: str, base_url: str
    ) -> Optional[ParsedDocument]:
        import httpx
        url = base_url.rstrip("/") + "/parse"
        with open(path, "rb") as fh:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    url,
                    files={
                        "file": (path.name, fh, "application/octet-stream")
                    },
                    data={"original_name": fallback},
                )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return _build_parsed_document(data)

    async def _parse_remote_batch(
        self, items: list[tuple[str, str]], base_url: str
    ) -> list[Optional[ParsedDocument]]:
        import json as _json
        import httpx
        url = base_url.rstrip("/") + "/parse-batch"
        files = []
        names = []
        handles = []
        try:
            for file_path, original_name in items:
                p = Path(file_path)
                fh = open(p, "rb")
                handles.append(fh)
                files.append(
                    ("files", (p.name, fh, "application/octet-stream"))
                )
                names.append(original_name or p.name)

            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    url,
                    files=files,
                    data={"original_names": _json.dumps(names)},
                )
            resp.raise_for_status()
        finally:
            for fh in handles:
                fh.close()

        results: list[Optional[ParsedDocument]] = []
        for data in resp.json():
            if "error" in data:
                log(f"WARN Remote item error: {data['error'][:120]}")
                results.append(None)
            else:
                results.append(_build_parsed_document(data))
        return results

    # ------------------------------------------------------------------
    # Local PyMuPDF fallback
    # ------------------------------------------------------------------

    async def _parse_fallback(
        self, path: Path, fallback: str
    ) -> Optional[ParsedDocument]:
        text = await _extract_plain_text(path)
        if not text:
            return None
        sections = _sections_from_markdown(text)
        title = fallback.replace('_', ' ').replace('-', ' ').title()
        return ParsedDocument(
            title=title,
            sections=sections,
            full_markdown=text,
            page_count=1,
            file_type=path.suffix.lower().lstrip('.'),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_parsed_document(data: dict) -> ParsedDocument:
    return ParsedDocument(
        title=data["title"],
        sections=[_dict_to_section(s) for s in data["sections"]],
        full_markdown=data["full_markdown"],
        page_count=data["page_count"],
        file_type=data["file_type"],
        metadata=data.get("metadata", {}),
    )


def _dict_to_section(d: dict) -> ParsedSection:
    return ParsedSection(
        title=d["title"],
        level=d["level"],
        content=d["content"],
        page_start=d.get("page_start", 0),
        page_end=d.get("page_end", 0),
        section_index=d.get("section_index", 0),
        subsections=[_dict_to_section(s) for s in d.get("subsections", [])],
    )


def _sections_from_markdown(markdown: str) -> list:
    """Build a flat list of ParsedSection from a markdown string."""
    lines = markdown.splitlines()
    sections: list[ParsedSection] = []
    section_index = 0

    current_title: Optional[str] = None
    current_level: int = 1
    current_lines: list[str] = []
    current_page_start: int = 0

    def flush() -> None:
        nonlocal section_index
        has_content = any(ln.strip() for ln in current_lines)
        if current_title is None and not has_content:
            return
        content = "\n".join(current_lines).strip()
        sections.append(ParsedSection(
            title=current_title or "Introduction",
            level=current_level,
            content=content,
            page_start=current_page_start,
            page_end=current_page_start,
            section_index=section_index,
        ))
        section_index += 1
        current_lines.clear()

    in_fence = False
    for line in lines:
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
        heading = (
            re.match(r'^(#{1,6})\s+(.+)$', line) if not in_fence else None
        )
        if heading:
            flush()
            current_title = heading.group(2).strip()
            current_level = len(heading.group(1))
            current_page_start = 0
        else:
            if current_title is None and line.strip():
                current_title = None
            current_lines.append(line)

    flush()

    if not sections:
        content = markdown.strip()
        if content:
            sections.append(ParsedSection(
                title="Document Content",
                level=1,
                content=content,
                section_index=0,
            ))
    return sections


def _extract_pdf_structured(path: Path) -> Optional[str]:
    """Extract text from PDF with font-based heading detection via PyMuPDF."""
    from collections import Counter
    import fitz

    with fitz.open(str(path)) as pdf:
        sizes: list[float] = []
        for page in pdf:
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            sizes.append(span["size"])

        if not sizes:
            return None

        counts = Counter(round(s, 1) for s in sizes)
        body_size: float = counts.most_common(1)[0][0]
        if body_size <= 0:
            body_size = 10.0

        lines: list[str] = []
        for page in pdf:
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    spans = line["spans"]
                    text = " ".join(s["text"] for s in spans).strip()
                    if not text:
                        continue
                    avg_size = (
                        sum(s["size"] for s in spans) / len(spans)
                        if spans else body_size
                    )
                    is_bold = any(s["flags"] & 16 for s in spans)
                    is_short = len(text) <= 120
                    is_allcaps = text.isupper() and len(text) > 3

                    if is_short and (
                        avg_size >= body_size * 1.8
                        or (is_bold and avg_size >= body_size * 1.4)
                        or is_allcaps
                    ):
                        lines.append(f"# {text}")
                    elif is_short and avg_size >= body_size * 1.35:
                        lines.append(f"## {text}")
                    elif is_short and avg_size >= body_size * 1.15:
                        lines.append(f"### {text}")
                    else:
                        lines.append(text)

            lines.append("")

    return "\n".join(lines) or None


async def _extract_plain_text(path: Path) -> Optional[str]:
    """Last-resort plain text extraction (PDF via PyMuPDF, text files)."""
    ext = path.suffix.lower()

    if ext == '.pdf':
        try:
            return _extract_pdf_structured(path)
        except Exception as exc:
            log(f"PyMuPDF error: {exc}")
            return None

    if ext in ('.txt', '.md', '.markdown', '.html', '.htm'):
        try:
            return path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            return path.read_text(encoding='latin-1')

    return None
