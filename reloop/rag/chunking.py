"""Text extraction, cleaning and chunking for knowledge documents.

Chunks follow the document's sections: a chunk never spans two headings, each chunk
records the heading it belongs to, and long sections are split on paragraph or
sentence boundaries with a short overlap that always starts at a sentence.
"""

import re
from pathlib import Path

from reloop.models.knowledge import Chunk

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}
TARGET_CHARS = 1200
OVERLAP_CHARS = 200
MIN_CHUNK_CHARS = 80

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
_PLAIN_HEADING = re.compile(r"^(?:[A-Z0-9][A-Z0-9 ,.\-()/&]{6,80}|\d+(?:\.\d+)*\.?\s+[A-Z][^.]{3,80})$")
_LINE_JOIN = re.compile(r"\n(?!\s*(?:\([a-zA-Z0-9]{1,4}\)|[•\-–]|\d{1,2}[.)])\s)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+(?=[A-Z0-9(\"'])")


def extract_pages(path: Path) -> list[str]:
    """Return the document text as a list of pages (one entry for non-PDF files)."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.name} (use PDF, TXT or MD)")
    if suffix == ".pdf":
        from pypdf import PdfReader  # ingestion-only dependency

        reader = PdfReader(str(path))
        return [(page.extract_text() or "") for page in reader.pages]
    return [path.read_text(encoding="utf-8", errors="replace")]


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)  # re-join words hyphenated across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _blocks(text: str) -> list[tuple[str, str]]:
    """Split cleaned text into ("heading"|"para", text) blocks."""
    out: list[tuple[str, str]] = []
    for raw in re.split(r"\n\s*\n", text):
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n")
        # A markdown heading may sit directly above its paragraph.
        md = _MD_HEADING.match(lines[0])
        if md:
            out.append(("heading", md.group(1).strip()))
            raw = "\n".join(lines[1:]).strip()
            if not raw:
                continue
        elif len(lines) == 1 and len(raw) <= 90 and _PLAIN_HEADING.match(raw):
            out.append(("heading", raw))
            continue
        # PDFs break lines mid-sentence: re-join them, but keep list items on their own lines.
        joined = _LINE_JOIN.sub(" ", raw)
        out.append(("para", re.sub(r" {2,}", " ", joined).strip()))
    return out


def _overlap(content: str) -> str:
    window = content[-OVERLAP_CHARS:]
    parts = _SENTENCE_SPLIT.split(window, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def chunk_pages(pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    multi_page = len(pages) > 1
    heading: str | None = None
    buf: list[str] = []
    buf_page: int | None = None
    carried = False  # buffer currently holds only overlap text

    def emit(continue_section: bool) -> None:
        nonlocal buf, buf_page, carried
        content = "\n\n".join(buf).strip()
        if len(content) >= MIN_CHUNK_CHARS and not carried:
            chunks.append(Chunk(index=len(chunks), content=content, heading=heading, page_from=buf_page))
        tail = _overlap(content) if continue_section and not carried else ""
        buf, carried = ([tail], True) if tail else ([], False)
        if not tail:
            buf_page = None

    for page_no, page in enumerate(pages, start=1):
        for kind, text in _blocks(clean_text(page)):
            if kind == "heading":
                if buf:
                    emit(continue_section=False)
                heading = text
                continue
            pieces = [text] if len(text) <= TARGET_CHARS else _SENTENCE_SPLIT.split(text)
            for piece in pieces:
                size = sum(len(b) + 2 for b in buf)
                if buf and size + len(piece) > TARGET_CHARS and not carried:
                    emit(continue_section=True)
                if not buf or carried and len(buf) == 1:
                    buf_page = buf_page or (page_no if multi_page else None)
                buf.append(piece)
                carried = False
    if buf:
        emit(continue_section=False)
    return chunks
