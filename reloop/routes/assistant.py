"""Smart disposal assistant (RAG)."""

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from reloop.config import get_settings
from reloop.models.knowledge import Answer, AnswerMode
from reloop.rag.answer import KnowledgeAssistant, get_generator
from reloop.rag.embeddings import get_embedder
from reloop.rag.store import StoreError, get_store
from reloop.routes.deps import rate_limiter
from reloop.templating import templates

router = APIRouter()
log = logging.getLogger("reloop.assistant")

EXAMPLES = [
    "How should I dispose of old batteries?",
    "Where do expired medicines go?",
    "Can I put a broken mobile phone in dry waste?",
]

# Tests inject a ready KnowledgeAssistant here.
_assistant_override: KnowledgeAssistant | None = None


def _status() -> tuple[KnowledgeAssistant | None, str, int]:
    """Returns (assistant, state, document_count). state: unconfigured | empty | ready | error."""
    if _assistant_override is not None:
        return _assistant_override, "ready", _assistant_override.store.document_count()
    settings = get_settings()
    store, embedder = get_store(settings), get_embedder(settings)
    if store is None or embedder is None:
        return None, "unconfigured", 0
    try:
        count = store.document_count()
    except StoreError:
        return None, "error", 0
    if count == 0:
        return None, "empty", 0
    return KnowledgeAssistant(store, embedder, get_generator(settings), settings), "ready", count


def _render(request: Request, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "assistant.html",
        {"active": "assistant", "examples": EXAMPLES, "modes": AnswerMode, **ctx},
        status_code=status_code,
    )


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, question: str = "") -> HTMLResponse:
    _, state, count = _status()
    return _render(request, state=state, doc_count=count, question=" ".join(question.split())[:500] or None)


@router.post("/assistant", response_class=HTMLResponse)
def assistant_ask(request: Request, question: str = Form("")) -> HTMLResponse:
    assistant, state, count = _status()
    question = question.strip()
    if not question:
        return _render(request, 422, state=state, doc_count=count, error="Please type a question first.")
    if len(question) > 500:
        return _render(request, 422, state=state, doc_count=count, question=question[:500],
                       error="Please keep your question under 500 characters.")
    if assistant is None:
        answer = Answer(mode=AnswerMode.UNAVAILABLE, question=question,
                        message="The knowledge base isn't ready yet, so we can't answer from verified sources.")
    else:
        limited = rate_limiter().check(request, "assistant")  # each answer is a paid AI call
        if limited:
            return _render(request, 429, state=state, doc_count=count, question=question, error=limited)
        answer = assistant.answer(question)
    log.info("assistant mode=%s sources=%d", answer.mode, len(answer.sources))
    return _render(request, state=state, doc_count=count, question=question, answer=answer)
