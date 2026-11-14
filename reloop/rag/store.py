"""Knowledge storage: Supabase pgvector in production, in-memory for tests."""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Protocol

import httpx

from reloop.config import Settings
from reloop.models.knowledge import Chunk, DocumentMeta, RetrievedChunk

log = logging.getLogger("reloop.store")


class StoreError(RuntimeError):
    """Knowledge store failed. Message is safe to show users."""


class KnowledgeStore(Protocol):
    def document_count(self) -> int: ...

    def upsert_document(self, meta: DocumentMeta, sha256: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def search(self, embedding: list[float], k: int, min_similarity: float) -> list[RetrievedChunk]: ...


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InMemoryStore:
    def __init__(self) -> None:
        self.docs: dict[str, DocumentMeta] = {}
        self.rows: list[tuple[str, Chunk, list[float]]] = []

    def document_count(self) -> int:
        return len(self.docs)

    def upsert_document(self, meta: DocumentMeta, sha256: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.docs[sha256] = meta
        self.rows = [r for r in self.rows if r[0] != sha256]
        self.rows.extend((sha256, c, e) for c, e in zip(chunks, embeddings, strict=True))

    def search(self, embedding: list[float], k: int, min_similarity: float) -> list[RetrievedChunk]:
        def cos(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
            return dot / (na * nb) if na and nb else 0.0

        scored = [(cos(embedding, e), sha, c) for sha, c, e in self.rows]
        scored = [s for s in scored if s[0] >= min_similarity]
        scored.sort(key=lambda s: s[0], reverse=True)
        out = []
        for sim, sha, c in scored[:k]:
            m = self.docs[sha]
            out.append(RetrievedChunk(content=c.content, similarity=round(sim, 4), title=m.title, publisher=m.publisher,
                                      source_url=m.source_url, published_on=m.published_on, heading=c.heading,
                                      page_from=c.page_from, chunk_index=c.index))
        return out


def _vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


class SupabaseStore:
    """Talks to Supabase's REST API (PostgREST) with the server-only service-role key."""

    def __init__(self, url: str, service_role_key: str, timeout_s: float = 20.0):
        self._base = url.rstrip("/") + "/rest/v1"
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout_s

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {**self._headers, **kw.pop("headers", {})}
        try:
            r = httpx.request(method, self._base + path, headers=headers, timeout=self._timeout, **kw)
        except httpx.HTTPError:
            log.error("supabase connection error on %s", path)
            raise StoreError("We couldn't reach the knowledge base. Please try again shortly.") from None
        if r.status_code >= 400:
            log.error("supabase error %s on %s: %s", r.status_code, path, r.text[:300])
            raise StoreError("The knowledge base had a problem. Please try again shortly.")
        return r

    def document_count(self) -> int:
        r = self._request("HEAD", "/knowledge_documents?status=eq.active&select=id",
                          headers={"Prefer": "count=exact", "Range": "0-0"})
        total = r.headers.get("content-range", "*/0").split("/")[-1]
        return int(total) if total.isdigit() else 0

    def upsert_document(self, meta: DocumentMeta, sha256: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        doc = {**meta.model_dump(), "content_sha256": sha256, "chunk_count": len(chunks), "status": "active"}
        r = self._request("POST", "/knowledge_documents?on_conflict=content_sha256", json=doc,
                          headers={"Prefer": "resolution=merge-duplicates,return=representation"})
        doc_id = r.json()[0]["id"]
        self._request("DELETE", f"/knowledge_chunks?document_id=eq.{doc_id}")
        rows = [
            {"document_id": doc_id, "chunk_index": c.index, "content": c.content, "heading": c.heading,
             "page_from": c.page_from, "embedding": _vector_literal(e)}
            for c, e in zip(chunks, embeddings, strict=True)
        ]
        for start in range(0, len(rows), 100):
            self._request("POST", "/knowledge_chunks", json=rows[start:start + 100], headers={"Prefer": "return=minimal"})

    def search(self, embedding: list[float], k: int, min_similarity: float) -> list[RetrievedChunk]:
        r = self._request("POST", "/rpc/match_knowledge_chunks", json={
            "query_embedding": _vector_literal(embedding), "match_count": k, "min_similarity": min_similarity,
        })
        return [RetrievedChunk(**row) for row in r.json()]


def get_store(settings: Settings) -> KnowledgeStore | None:
    if settings.supabase_url.strip() and settings.supabase_service_role_key.strip():
        return SupabaseStore(settings.supabase_url.strip(), settings.supabase_service_role_key.strip())
    return None
