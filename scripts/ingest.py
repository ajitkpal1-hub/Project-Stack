"""Load knowledge documents into the RAG knowledge base.

Usage (from the project root):
    .venv/Scripts/python scripts/ingest.py            # ingest everything listed in knowledge/manifest.toml
    .venv/Scripts/python scripts/ingest.py --dry-run  # extract and chunk only; no API calls, nothing stored

Every file must have an entry in knowledge/manifest.toml with at least a title, so
answers can name their source. Nothing is invented: unknown fields stay empty.
Needs SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EMBEDDING_PROVIDER=voyage and
EMBEDDING_API_KEY in .env (except for --dry-run).
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reloop.config import get_settings  # noqa: E402
from reloop.models.knowledge import DocumentMeta  # noqa: E402
from reloop.rag.chunking import SUPPORTED_SUFFIXES, chunk_pages, drop_mostly_devanagari, extract_pages  # noqa: E402
from reloop.rag.embeddings import get_embedder  # noqa: E402
from reloop.rag.store import get_store, sha256_of  # noqa: E402

KNOWLEDGE_DIR = ROOT / "knowledge"


def load_manifest(path: Path) -> tuple[dict[str, DocumentMeta], set[str]]:
    """Returns document facts by file name, plus the files marked english_only."""
    if not path.exists():
        return {}, set()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out, english_only = {}, set()
    for entry in data.get("document", []):
        entry = dict(entry)
        flag = bool(entry.pop("english_only", False))  # loading option, not stored with the document
        meta = DocumentMeta(**entry)
        out[meta.file_name] = meta
        if flag:
            english_only.add(meta.file_name)
    return out, english_only


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=KNOWLEDGE_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    folder: Path = args.dir
    manifest, english_only = load_manifest(folder / "manifest.toml")
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES and p.name.lower() != "readme.md")
    if not files:
        print(f"No PDF/TXT/MD files found in {folder}. The knowledge base stays empty.")
        return 0

    missing = [f.name for f in files if f.name not in manifest]
    if missing:
        print("These files have no entry in manifest.toml (add at least a title):")
        for name in missing:
            print(f"  - {name}")
        return 1

    settings = get_settings()
    embedder = store = None
    if not args.dry_run:
        embedder, store = get_embedder(settings, bulk=True), get_store(settings)
        if embedder is None or store is None:
            print("Missing configuration. Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EMBEDDING_PROVIDER=voyage and EMBEDDING_API_KEY in .env.")
            return 1

    for path in files:
        meta = manifest[path.name]
        pages = extract_pages(path)
        chunks = chunk_pages(pages)
        dropped = 0
        if path.name in english_only:
            before = len(chunks)
            chunks = drop_mostly_devanagari(chunks)
            dropped = before - len(chunks)
        chars = sum(len(c.content) for c in chunks)
        if not chunks and dropped:
            print(f"! {path.name}: only Hindi text found and english_only is set. Skipped.")
            continue
        if not chunks:
            print(f"! {path.name}: no text extracted (scanned PDF? it needs OCR first). Skipped.")
            continue
        note = f" (skipped {dropped} Hindi chunks: english_only)" if dropped else ""
        print(f"- {path.name}: {len(pages)} page(s), {len(chunks)} chunks, {chars:,} characters{note}")
        if args.dry_run:
            continue
        embeddings = embedder.embed([c.content for c in chunks], input_type="document")
        store.upsert_document(meta, sha256_of(path.read_bytes()), chunks, embeddings)
        print(f"  stored as '{meta.title}' (embeddings: {embedder.name})")

    if not args.dry_run:
        print(f"Done. Active documents in knowledge base: {store.document_count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
