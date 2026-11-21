"""Internal API for scheduled jobs (n8n). No pages, no links, not for the public.

  POST /api/internal/reel   {"topic"?: key, "avoid"?: [keys]}  -> a reviewed reel-script draft + a sheet row

Every request needs X-Reloop-Internal-Key (INTERNAL_API_SECRET, 32+ characters, else the API is off).
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reloop.config import get_settings
from reloop.rag.embeddings import EmbeddingError, get_embedder
from reloop.rag.store import StoreError, get_store
from reloop.routes.deps import rate_limiter
from reloop.services.reels import IST, TOPICS, TOPICS_BY_KEY, ReelWriter, ReelWriterError, get_reel_writer, make_reel, pick_topic, sheet_row

router = APIRouter(prefix="/api/internal")
log = logging.getLogger("reloop.internal")
SECRET_HEADER = "x-reloop-internal-key"

# Tests swap these in.
_writer_override: ReelWriter | None = None
_knowledge_override: tuple | None = None  # (store, embedder)


class ReelIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str | None = None
    avoid: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("topic", mode="before")
    @classmethod
    def _blank(cls, v: object) -> object:
        return None if v is None or str(v).strip() == "" else str(v).strip().lower()


def _reply(status_code: int, status: str, message: str, **fields) -> JSONResponse:
    return JSONResponse({"status": status, "message": message, **fields}, status_code=status_code,
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def _authorised(request: Request) -> JSONResponse | None:
    settings = get_settings()
    if not settings.internal_api_ready:
        return _reply(503, "unavailable", "The internal API is switched off (INTERNAL_API_SECRET not set).")
    given = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(given.encode(), settings.internal_api_secret.strip().encode()):
        log.warning("internal API call with missing or wrong key")
        return _reply(401, "unauthorised", "Not allowed.")
    return None


@router.post("/reel")
async def reel(request: Request) -> JSONResponse:
    if (refusal := _authorised(request)) is not None:
        return refusal
    try:
        body = await request.json()
    except ValueError:
        body = {}
    try:
        parsed = ReelIn.model_validate(body if isinstance(body, dict) else {})
    except ValidationError:
        return _reply(422, "invalid", "Body must be {\"topic\": optional topic key, \"avoid\": optional list of keys}.")
    if parsed.topic and parsed.topic not in TOPICS_BY_KEY:
        return _reply(422, "invalid", "Unknown topic.", topics=[t.key for t in TOPICS])

    settings = get_settings()
    writer = _writer_override if _writer_override is not None else get_reel_writer(settings)
    store, embedder = _knowledge_override or (get_store(settings), get_embedder(settings))
    if writer is None:
        return _reply(503, "unavailable", "AI writing isn't switched on (LLM_PROVIDER).")
    if store is None or embedder is None:
        return _reply(503, "unavailable", "The knowledge base isn't configured, so there are no sources to write from.")
    limited = rate_limiter().check(request, "internal")
    if limited:
        return _reply(429, "busy", limited)

    topic = TOPICS_BY_KEY[parsed.topic] if parsed.topic else pick_topic(datetime.now(IST).date(), set(parsed.avoid))
    try:
        draft = make_reel(topic, store, embedder, writer, settings)
    except (EmbeddingError, StoreError):
        log.exception("reel: knowledge base unavailable")
        return _reply(503, "unavailable", "Couldn't reach the knowledge base. Try again later.", topic=topic.key)
    except ReelWriterError as e:
        return _reply(503, "unavailable", str(e), topic=topic.key)

    return _reply(200, draft.status.value, f"{topic.title}: {draft.status.value}", topic=topic.key,
                  draft=draft.model_dump(mode="json"), sheet_row=sheet_row(draft, datetime.now(timezone.utc)))
