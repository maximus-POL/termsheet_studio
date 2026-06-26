from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PDFExtractionError(RuntimeError):
    pass


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise PDFExtractionError(f"PDF does not exist: {pdf_path}")

    try:
        import fitz
    except ImportError as exc:
        raise PDFExtractionError(
            "PyMuPDF is not installed. Run: pip install -r requirements.txt"
        ) from exc

    page_text: list[str] = []

    try:
        with fitz.open(pdf_path) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text")
                logger.debug("Extracted %s characters from page %s", len(text), page_number)
                page_text.append(text)
    except Exception as exc:
        raise PDFExtractionError(f"Could not extract text from {pdf_path.name}: {exc}") from exc

    extracted = "\n".join(page_text).strip()
    if not extracted:
        raise PDFExtractionError(
            f"No text extracted from {pdf_path.name}. The PDF may be scanned or image-only."
        )

    return extracted
