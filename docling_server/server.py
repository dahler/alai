"""
Standalone Docling parse server.
Run on Mac Mini (or any machine) and point the Windows backend at it.

Start:  uvicorn server:app --host 0.0.0.0 --port 7777
"""

import dataclasses
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

# Module-level converter cache — loaded once at startup, reused forever.
_converter_pdf = None
_converter_other = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _converter_pdf, _converter_other
    log("Loading Docling models (PDF)...")
    _converter_pdf = _make_converter(has_pdf=True)
    log("Loading Docling models (other formats)...")
    _converter_other = _make_converter(has_pdf=False)
    log("Models ready.")
    yield


app = FastAPI(title="Docling Parse Server", lifespan=lifespan)


def _get_converter(file_path: str):
    return (
        _converter_pdf
        if Path(file_path).suffix.lower() == ".pdf"
        else _converter_other
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [DOCLING-SERVER] {msg}")


# ---------------------------------------------------------------------------
# Data classes (mirrors docling_service.py)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ParsedSection:
    title: str
    level: int
    content: str
    page_start: int = 0
    page_end: int = 0
    section_index: int = 0
    subsections: list = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def _detect_device():
    from docling.datamodel.pipeline_options import AcceleratorDevice
    try:
        import torch
        if torch.cuda.is_available():
            log(f"CUDA GPU: {torch.cuda.get_device_name(0)}")
            return AcceleratorDevice.CUDA
        if torch.backends.mps.is_available():
            log("Apple Silicon MPS")
            return AcceleratorDevice.MPS
    except Exception:
        pass
    log("CPU only")
    return AcceleratorDevice.CPU


def _make_converter(has_pdf: bool):
    from docling.document_converter import DocumentConverter
    if not has_pdf:
        return DocumentConverter()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice, AcceleratorOptions, PdfPipelineOptions,
    )
    from docling.document_converter import PdfFormatOption

    device = _detect_device()
    on_gpu = device in (AcceleratorDevice.CUDA, AcceleratorDevice.MPS)

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = False
    pdf_options.do_table_structure = True
    pdf_options.layout_batch_size = 4 if on_gpu else 1
    pdf_options.images_scale = 0.75 if on_gpu else 0.5
    pdf_options.accelerator_options = AcceleratorOptions(
        device=device,
        num_threads=2,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options)
        }
    )


# ---------------------------------------------------------------------------
# Docling helpers
# ---------------------------------------------------------------------------

def _title_from_doc(doc, fallback: str) -> str:
    first_section_header: Optional[str] = None
    try:
        for item in doc.texts:
            label = str(getattr(item, "label", "")).split(".")[-1].lower()
            text = (getattr(item, "text", "") or "").strip()
            if not text or len(text) <= 3:
                continue
            if label == "title":
                return text[:200]
            if label == "section_header" and first_section_header is None:
                first_section_header = text[:200]
    except Exception:
        pass
    if first_section_header:
        return first_section_header
    return fallback.replace("_", " ").replace("-", " ").title()


def _page_count_from_doc(doc) -> int:
    try:
        max_page = 0
        for item in doc.texts:
            for prov in getattr(item, "prov", []) or []:
                max_page = max(max_page, getattr(prov, "page_no", 0))
        return max(max_page, 1)
    except Exception:
        return 1


def _sections_from_markdown(markdown: str) -> list:
    lines = markdown.splitlines()
    sections: list[ParsedSection] = []
    section_index = 0

    current_title: Optional[str] = None
    current_level: int = 1
    current_lines: list[str] = []
    current_page_start: int = 0

    def flush() -> None:
        nonlocal section_index
        if current_title is None and not any(
            ln.strip() for ln in current_lines
        ):
            return
        title = current_title or "Introduction"
        content = "\n".join(current_lines).strip()
        sections.append(ParsedSection(
            title=title,
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
            re.match(r"^(#{1,6})\s+(.+)$", line) if not in_fence else None
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


def _convert(file_path: str, original_name: str) -> dict:
    converter = _get_converter(file_path)
    result = converter.convert(file_path)
    doc = result.document
    markdown = doc.export_to_markdown()
    ext = Path(file_path).suffix.lower()
    return {
        "title": _title_from_doc(doc, original_name),
        "sections": [
            dataclasses.asdict(s)
            for s in _sections_from_markdown(markdown)
        ],
        "full_markdown": markdown,
        "page_count": _page_count_from_doc(doc),
        "file_type": ext.lstrip("."),
        "metadata": {"source": Path(file_path).name},
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/parse")
async def parse_single(
    file: UploadFile = File(...),
    original_name: str = Form(""),
):
    t0 = time.time()
    suffix = Path(file.filename or "upload").suffix or ".bin"
    name = original_name or file.filename or "document"
    log(f"Parsing {name}")

    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False
    ) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        data = _convert(tmp_path, Path(name).stem)
        log(
            f"OK {name}: {len(data['sections'])} sections "
            f"in {time.time() - t0:.2f}s"
        )
        return JSONResponse(content=data)
    except Exception as exc:
        import traceback
        log(f"ERROR {name}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": f"{exc}\n{traceback.format_exc()}"},
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/parse-batch")
async def parse_batch(
    files: list[UploadFile] = File(...),
    original_names: str = Form("[]"),
):
    import json
    try:
        names: list[str] = json.loads(original_names)
    except Exception:
        names = []

    # Pad names list to match files
    while len(names) < len(files):
        names.append("")

    results = []
    for upload, name in zip(files, names):
        t0 = time.time()
        suffix = Path(upload.filename or "upload").suffix or ".bin"
        display = name or upload.filename or "document"
        log(f"Parsing {display}")

        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False
        ) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name

        try:
            data = _convert(tmp_path, Path(display).stem)
            log(
                f"OK {display}: {len(data['sections'])} sections "
                f"in {time.time() - t0:.2f}s"
            )
            results.append(data)
        except Exception as exc:
            import traceback
            log(f"ERROR {display}: {exc}")
            results.append(
                {"error": f"{exc}\n{traceback.format_exc()}"}
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return JSONResponse(content=results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7777)
