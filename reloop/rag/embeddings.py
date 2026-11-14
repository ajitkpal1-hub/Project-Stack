"""Embedding providers. Configurable via EMBEDDING_PROVIDER.

- voyage: Voyage AI REST API (default model voyage-4, 1024 dimensions).
- hash: deterministic word-hashing vectors for tests and offline development only.
  It captures word overlap, not meaning, and must never be used in production.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Literal, Protocol

import httpx

from reloop.config import Settings

log = logging.getLogger("reloop.embeddings")

DIMENSIONS = 1024  # must match vector(1024) in supabase/migrations
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
DEFAULT_VOYAGE_MODEL = "voyage-4"
InputType = Literal["query", "document"]


class EmbeddingError(RuntimeError):
    """Embedding service failed. Message is safe to show users."""


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


class VoyageEmbedder:
    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 30.0):
        self.name = model or DEFAULT_VOYAGE_MODEL
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_s

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), 128):  # well under Voyage's 1,000 inputs / 320K tokens per request
            batch = texts[start:start + 128]
            payload = {"input": batch, "model": self.name, "input_type": input_type, "output_dimension": DIMENSIONS}
            try:
                r = httpx.post(VOYAGE_URL, json=payload, headers=self._headers, timeout=self._timeout)
            except httpx.HTTPError:
                log.error("voyage connection error")
                raise EmbeddingError("We couldn't reach the search service. Please try again shortly.") from None
            if r.status_code != 200:
                log.error("voyage error status=%s", r.status_code)
                raise EmbeddingError("The search service had a problem. Please try again shortly.")
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out


class HashEmbedder:
    """Bag-of-words hashing. For tests/dev only."""

    name = "hash-dev"

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * DIMENSIONS
        for word in re.findall(r"[a-z0-9]{3,}", text.lower()):
            h = int.from_bytes(hashlib.md5(word.encode()).digest()[:4], "little")
            vec[h % DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_embedder(settings: Settings) -> Embedder | None:
    provider = settings.embedding_provider.strip().strip("\"'").lower()
    if provider == "voyage" and settings.embedding_api_key.strip():
        return VoyageEmbedder(settings.embedding_api_key.strip(), settings.embedding_model.strip() or None)
    if provider == "hash":
        return HashEmbedder()
    return None
