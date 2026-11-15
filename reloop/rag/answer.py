"""Grounded question answering over the knowledge base.

retrieve -> (nothing relevant? say so) -> Claude with citations -> keep only cited text.
Without an LLM, matching passages are shown verbatim instead of a generated answer.
Model knowledge is never presented as a sourced answer.
"""

from __future__ import annotations

import logging
from typing import Protocol

from reloop.config import Settings
from reloop.models.knowledge import Answer, AnswerMode, AnswerSegment, RetrievedChunk
from reloop.rag.embeddings import Embedder, EmbeddingError
from reloop.rag.store import KnowledgeStore, StoreError

log = logging.getLogger("reloop.rag")

NO_SOURCE_MESSAGE = (
    "We couldn't find this in the documents we've loaded, so we won't guess. "
    "Please check with your local municipal office, or scan the item for general guidance."
)

ANSWER_SYSTEM = """You answer household waste questions for RELOOP AI (India; pilot area Thakurli, Dombivli and Kalyan).

Use ONLY the provided documents. Every factual sentence must be supported by a citation to them.
If the documents do not answer the question, reply exactly: NOT_IN_SOURCES
Do not add facts, rules, phone numbers, organisations or links that are not in the documents.
If the documents disagree with each other, say so and cite both.
Put safety first: mention hazards the documents describe.
Write 2-6 short sentences of plain English for a household. No headings, no markdown."""


class Generator(Protocol):
    def generate(self, question: str, passages: list[RetrievedChunk]) -> list[AnswerSegment] | None:
        """Return cited segments, or None when the sources don't answer the question."""
        ...


class ClaudeGenerator:
    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 60.0):
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
        self._model = model or "claude-opus-5-5"

    def generate(self, question: str, passages: list[RetrievedChunk]) -> list[AnswerSegment] | None:
        anthropic = self._anthropic
        documents = [
            {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": p.content},
                "title": p.title,
                "context": " · ".join(x for x in [p.publisher, p.published_on, p.heading] if x) or None,
                "citations": {"enabled": True},
            }
            for p in passages
        ]
        for d in documents:
            if d["context"] is None:
                del d["context"]
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "medium"},
                system=ANSWER_SYSTEM,
                messages=[{"role": "user", "content": [*documents, {"type": "text", "text": question[:500]}]}],
            )
        except anthropic.APIStatusError as e:
            log.error("answer API error %s", e.status_code)
            raise GenerationError("The assistant had a problem. Please try again shortly.") from None
        except anthropic.APIConnectionError:
            log.error("answer connection error")
            raise GenerationError("We couldn't reach the assistant. Please try again shortly.") from None

        log.info("answered model=%s stop=%s in=%s out=%s", response.model, response.stop_reason,
                 response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "refusal":
            raise GenerationError("The assistant declined this question. Please rephrase it.")

        segments: list[AnswerSegment] = []
        for block in response.content:
            if block.type != "text":
                continue
            if "NOT_IN_SOURCES" in block.text:
                return None
            numbers = sorted({c.document_index + 1 for c in (block.citations or [])})
            segments.append(AnswerSegment(text=block.text, source_numbers=numbers))
        return segments


class GenerationError(RuntimeError):
    pass


class KnowledgeAssistant:
    def __init__(self, store: KnowledgeStore, embedder: Embedder, generator: Generator | None, settings: Settings):
        self.store, self.embedder, self.generator, self.settings = store, embedder, generator, settings

    def answer(self, question: str) -> Answer:
        question = " ".join(question.split())[:500]
        try:
            [vector] = self.embedder.embed([question], input_type="query")
            passages = self.store.search(vector, k=self.settings.rag_top_k, min_similarity=self.settings.rag_min_similarity)
        except (EmbeddingError, StoreError) as e:
            return Answer(mode=AnswerMode.UNAVAILABLE, question=question, message=str(e))

        if not passages:
            return Answer(mode=AnswerMode.NO_SOURCE, question=question, message=NO_SOURCE_MESSAGE)

        if self.generator is None:
            return Answer(mode=AnswerMode.PASSAGES, question=question, sources=passages,
                          message="AI answers aren't switched on, so here are the most relevant passages from our sources.")

        try:
            segments = self.generator.generate(question, passages)
        except GenerationError as e:
            return Answer(mode=AnswerMode.PASSAGES, question=question, sources=passages,
                          message=f"{e} Meanwhile, here are the most relevant passages from our sources.")

        if segments is None:
            return Answer(mode=AnswerMode.NO_SOURCE, question=question, message=NO_SOURCE_MESSAGE)

        # Keep connective text, but if nothing at all is cited the answer isn't grounded.
        if not any(s.source_numbers for s in segments):
            return Answer(mode=AnswerMode.NO_SOURCE, question=question, message=NO_SOURCE_MESSAGE)

        used = sorted({n for s in segments for n in s.source_numbers})
        renumber = {old: new for new, old in enumerate(used, start=1)}
        for s in segments:
            s.source_numbers = [renumber[n] for n in s.source_numbers]
        return Answer(mode=AnswerMode.GROUNDED, question=question, segments=segments,
                      sources=[passages[n - 1] for n in used])


def get_generator(settings: Settings) -> Generator | None:
    if settings.llm_mode == "anthropic" and settings.llm_api_key.strip():
        return ClaudeGenerator(settings.llm_api_key.strip(), settings.llm_model.strip() or None)
    return None  # mock mode and unconfigured both fall back to verbatim passages


def get_assistant(settings: Settings, generate: bool = True) -> KnowledgeAssistant | None:
    """The knowledge assistant, or None when the store or embeddings aren't configured.
    generate=False skips the AI-written summary and returns matching passages (used by scans, for speed)."""
    from reloop.rag.embeddings import get_embedder
    from reloop.rag.store import get_store

    store, embedder = get_store(settings), get_embedder(settings)
    if store is None or embedder is None:
        return None
    return KnowledgeAssistant(store, embedder, get_generator(settings) if generate else None, settings)
