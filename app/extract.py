"""Text extraction from uploaded security documents."""

from __future__ import annotations

import csv
import io
from pathlib import PurePath
from typing import Tuple

# Formats we can turn into text locally.
TEXT_FORMATS = {".pdf", ".docx", ".xlsx", ".csv", ".txt"}
IMAGE_FORMATS = {".png", ".jpg", ".jpeg"}
# Legacy binary Office formats: stored, but not readable by the review.
UNREADABLE_FORMATS = {".doc", ".xls"}


def extract_text(filename: str, data: bytes) -> Tuple[str, str]:
    """Return (text, note). `note` explains why text is empty or partial."""
    ext = PurePath(filename).suffix.lower()
    try:
        if ext == ".pdf":
            return _pdf(data)
        if ext == ".docx":
            return _docx(data), ""
        if ext == ".xlsx":
            return _xlsx(data), ""
        if ext == ".csv":
            text = data.decode("utf-8-sig", errors="replace")
            rows = csv.reader(io.StringIO(text))
            return _join_rows([c for c in r if c.strip()] for r in rows), ""
        if ext == ".txt":
            return data.decode("utf-8-sig", errors="replace"), ""
        if ext in IMAGE_FORMATS:
            return "", "Image file: only the AI review can read it."
        if ext in UNREADABLE_FORMATS:
            return "", f"Legacy {ext} format can't be read; ask for PDF or {ext}x."
        return "", f"Unsupported format {ext}."
    except Exception as exc:  # corrupt or encrypted files
        return "", f"Could not read file ({type(exc).__name__}: {exc})."


def _pdf(data: bytes) -> Tuple[str, str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return "", "PDF is password-protected."
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        pages.append(f"[Page {i}]\n{page.extract_text() or ''}")
    text = "\n\n".join(pages)
    if len(text.replace("[Page", "").strip()) < 20 * max(1, len(reader.pages)):
        return text, "Little or no text layer (possibly scanned); the AI review reads the PDF directly."
    return text, ""


def _docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"[Sheet: {ws.title.strip()}]")
        parts.append(_join_rows([str(c) for c in row if c not in (None, "")] for row in ws.iter_rows(values_only=True)))
    return "\n\n".join(p for p in parts if p)


def _join_rows(rows) -> str:
    """One line per spreadsheet row, rows separated by a blank line.

    Line breaks inside a cell are collapsed, so each row (e.g. a questionnaire
    question with its answers) stays one passage for the keyword scan and
    reads cleanly for the AI review.
    """
    lines = []
    for cells in rows:
        cells = [" ".join(str(c).split()) for c in cells]
        cells = [c for c in cells if c]
        if cells:
            lines.append(" | ".join(cells))
    return "\n\n".join(lines)
