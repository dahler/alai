"""
Document extraction service for PDF and text files.
Extracts text content to send to the AI model.
"""

import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def log(message: str):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [DOCUMENT] {message}")


class DocumentService:
    """Service for extracting text from documents."""

    SUPPORTED_EXTENSIONS = {'.pdf', '.txt', '.md', '.json', '.xml', '.html', '.css', '.js'}

    async def extract_text(self, file_path: str) -> Optional[str]:
        """
        Extract text content from a document file.

        Args:
            file_path: Path to the document file

        Returns:
            Extracted text content or None if extraction fails
        """
        path = Path(file_path)
        log(f"Extracting from: {file_path}")
        log(f"Path exists: {path.exists()}")

        if not path.exists():
            log(f"✗ ERROR: File not found!")
            return None

        extension = path.suffix.lower()
        log(f"File extension: {extension}")

        try:
            if extension == '.pdf':
                return await self._extract_pdf(path)
            elif extension in {'.txt', '.md', '.json', '.xml', '.html', '.css', '.js'}:
                return await self._extract_text_file(path)
            else:
                log(f"✗ Unsupported file type: {extension}")
                return None
        except Exception as e:
            import traceback
            log(f"✗ Extraction error: {e}")
            log(traceback.format_exc())
            return None

    async def _extract_pdf(self, path: Path) -> Optional[str]:
        """Extract text from PDF file."""
        log(f"PDF extraction starting...")
        start_time = time.time()

        try:
            # Try PyMuPDF (fitz) first - it's fast and accurate
            import fitz  # PyMuPDF
            log(f"Using PyMuPDF (fitz) v{fitz.version[0]}")

            text_parts = []
            with fitz.open(path) as doc:
                page_count = len(doc)
                log(f"PDF has {page_count} page(s)")
                for page_num, page in enumerate(doc, 1):
                    text = page.get_text()
                    if text.strip():
                        text_parts.append(f"--- Page {page_num} ---\n{text}")
                        log(f"  Page {page_num}/{page_count}: {len(text)} chars")

            if text_parts:
                full_text = "\n\n".join(text_parts)
                elapsed = time.time() - start_time
                log(f"✓ SUCCESS: {len(full_text)} chars from {len(text_parts)} page(s) in {elapsed:.2f}s")
                return full_text
            else:
                log("⚠ WARNING: No text found in PDF (may be image-based)")
                return None

        except ImportError as e:
            log(f"⚠ PyMuPDF not installed: {e}")
            log("Trying pypdf as fallback...")
            # Fallback to pypdf
            try:
                from pypdf import PdfReader

                reader = PdfReader(path)
                text_parts = []
                for page_num, page in enumerate(reader.pages, 1):
                    text = page.extract_text()
                    if text and text.strip():
                        text_parts.append(f"--- Page {page_num} ---\n{text}")

                if text_parts:
                    full_text = "\n\n".join(text_parts)
                    elapsed = time.time() - start_time
                    log(f"✓ SUCCESS (pypdf): {len(full_text)} chars in {elapsed:.2f}s")
                    return full_text

            except ImportError:
                log("✗ ERROR: No PDF library installed!")
                log("Install with: pip install pymupdf")
                return None
        except Exception as e:
            import traceback
            log(f"✗ PDF extraction error: {e}")
            log(traceback.format_exc())
            return None

        return None

    async def _extract_text_file(self, path: Path) -> Optional[str]:
        """Extract text from plain text files."""
        log(f"Extracting text file: {path.name}")
        try:
            # Try UTF-8 first
            text = path.read_text(encoding='utf-8')
            log(f"✓ Extracted {len(text)} chars (UTF-8)")
            return text
        except UnicodeDecodeError:
            # Fallback to latin-1
            try:
                text = path.read_text(encoding='latin-1')
                log(f"✓ Extracted {len(text)} chars (latin-1 fallback)")
                return text
            except Exception as e:
                log(f"✗ Text extraction error: {e}")
                return None

    def truncate_text(self, text: str, max_chars: int = 15000) -> str:
        """
        Truncate text to fit within context limits.
        Tries to break at sentence boundaries.
        """
        if len(text) <= max_chars:
            return text

        # Find a good breaking point
        truncated = text[:max_chars]

        # Try to break at last sentence
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        break_point = max(last_period, last_newline)

        if break_point > max_chars * 0.8:  # Only if we don't lose too much
            truncated = truncated[:break_point + 1]

        return truncated + "\n\n[Document truncated due to length...]"
