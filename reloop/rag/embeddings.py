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
import time
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
    """Voyage REST client.

    Live requests (the assistant page) fail fast. Bulk mode (scripts/ingest.py) sends
    smaller batches and waits out rate limits (HTTP 429), because new Voyage accounts
    without billing are limited to roughly 3 requests and 10K tokens per minute.
    """

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 30.0, *,
                 max_retries: int = 0, max_batch_chars: int = 400_000, sleep=time.sleep):
        self.name = model or DEFAULT_VOYAGE_MODEL
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._max_batch_chars = max_batch_chars
        self._sleep = sleep

    def _batches(self, texts: list[str]) -> list[list[str]]:
        batches: list[list[str]] = []
        current: list[str] = []
        size = 0
        for text in texts:
            if current and (len(current) >= 128 or size + len(text) > self._max_batch_chars):
                batches.append(current)
                current, size = [], 0
            current.append(text)
            size += len(text)
        if current:
            batches.append(current)
        return batches

    def _post(self, payload: dict) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                r = httpx.post(VOYAGE_URL, json=payload, headers=self._headers, timeout=self._timeout)
            except httpx.HTTPError:
                log.error("voyage connection error")
                raise EmbeddingError("We couldn't reach the search service. Please try again shortly.") from None
            if r.status_code != 429 or attempt == self._max_retries:
                return r
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = 0.0
            wait = min(max(wait, 20.0 * (attempt + 1)), 120.0)
            log.warning("voyage rate limited; waiting %.0fs (retry %d of %d)", wait, attempt + 1, self._max_retries)
            self._sleep(wait)
        raise AssertionError("unreachable")

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        out: list[list[float]] = []
        for batch in self._batches(texts):  # well under Voyage's 1,000 inputs / 320K tokens per request
            payload = {"input": batch, "model": self.name, "input_type": input_type, "output_dimension": DIMENSIONS}
            r = self._post(payload)
            if r.status_code == 429:
                log.error("voyage error status=429 (rate limit)")
                raise EmbeddingError("The search service is busy (rate limit). Please try again in a minute.")
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


def get_embedder(settings: Settings, *, bulk: bool = False) -> Embedder | None:
    """bulk=True (ingestion) uses small batches and waits out rate limits."""
    provider = settings.embedding_provider.strip().strip("\"'").lower()
    if provider == "voyage" and settings.embedding_api_key.strip():
        model = settings.embedding_model.strip() or None
        if bulk:  # ~6K tokens per request keeps a free-tier key under 10K tokens/minute
            return VoyageEmbedder(settings.embedding_api_key.strip(), model, timeout_s=60.0, max_retries=8, max_batch_chars=24_000)
        return VoyageEmbedder(settings.embedding_api_key.strip(), model)
    if provider == "hash":
        return HashEmbedder()
    return None
