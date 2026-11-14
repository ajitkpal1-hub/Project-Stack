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
from reloop.rag.chunking import SUPPORTED_SUFFIXES, chunk_pages, extract_pages  # noqa: E402
from reloop.rag.embeddings import get_embedder  # noqa: E402
from reloop.rag.store import get_store, sha256_of  # noqa: E402

KNOWLEDGE_DIR = ROOT / "knowledge"


def load_manifest(path: Path) -> dict[str, DocumentMeta]:
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out = {}
    for entry in data.get("document", []):
        meta = DocumentMeta(**entry)
        out[meta.file_name] = meta
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=KNOWLEDGE_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    folder: Path = args.dir
    manifest = load_manifest(folder / "manifest.toml")
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
        embedder, store = get_embedder(settings), get_store(settings)
        if embedder is None or store is None:
            print("Missing configuration. Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EMBEDDING_PROVIDER=voyage and EMBEDDING_API_KEY in .env.")
            return 1

    for path in files:
        meta = manifest[path.name]
        pages = extract_pages(path)
        chunks = chunk_pages(pages)
        chars = sum(len(c.content) for c in chunks)
        if not chunks:
            print(f"! {path.name}: no text extracted (scanned PDF? it needs OCR first). Skipped.")
            continue
        print(f"- {path.name}: {len(pages)} page(s), {len(chunks)} chunks, {chars:,} characters")
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
