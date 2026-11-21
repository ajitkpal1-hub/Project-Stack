"""Voice API: JSON tools for the ElevenLabs voice agent.

The voice agent never answers from its own knowledge. It calls these three tools and
speaks what they return:

  POST /api/voice/ask       question      -> answer from the loaded official documents (cited)
  POST /api/voice/classify  description   -> which lane/bin, what to do, can it be donated
  POST /api/voice/centres   place, lane   -> verified centres first, map results labelled unverified

Every request must carry the shared secret in `X-Reloop-Voice-Key` (VOICE_TOOL_SECRET).
Answers run through the same guardrails and Safety Review as the website. Each response
has `say`: short plain sentences ready to be spoken, plus structured fields.
The caller's words are never logged.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reloop.agents.pipeline import WastePipeline
from reloop.config import get_settings
from reloop.models.categories import LANES_BY_CATEGORY, WasteCategory
from reloop.models.classification import Certainty, Condition
from reloop.models.knowledge import Answer, AnswerMode
from reloop.models.partners import KIND_LABELS
from reloop.models.pipeline import DonationStatus, PipelineResult
from reloop.rag.answer import KnowledgeAssistant, get_assistant
from reloop.routes.deps import partner_repo, partner_service, rate_limiter, record_usage
from reloop.services.classifier import Classifier, ClassifierUnavailable, get_classifier
from reloop.services.guardrails import item_unclear
from reloop.services.partners import DirectoryPartners

router = APIRouter(prefix="/api/voice")
log = logging.getLogger("reloop.voice")

SECRET_HEADER = "x-reloop-voice-key"
DEMO_PREFIX = "This is a demonstration answer, not a real AI result. "
OSM_ATTRIBUTION = "Map data from OpenStreetMap contributors (ODbL)."
CONDITION_QUESTION = "Before I say whether it can be donated: does it still work, and is it clean?"

# Tests swap these in without touching settings.
_classifier_override: Classifier | None = None
_assistant_override: KnowledgeAssistant | None = None


# ---------- request shapes ----------

def _one_line(v: object) -> str:
    return " ".join(str(v or "").split())


def _blank_to_none(v: object) -> object:
    return None if v is None or str(v).strip() == "" else str(v).strip().lower()


class AskIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field(min_length=2, max_length=500)

    @field_validator("question", mode="before")
    @classmethod
    def _clean(cls, v: object) -> str:
        return _one_line(v)


class ClassifyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = Field(min_length=2, max_length=300)
    condition: Condition | None = None  # only what the caller actually said

    @field_validator("description", mode="before")
    @classmethod
    def _clean(cls, v: object) -> str:
        return _one_line(v)

    @field_validator("condition", mode="before")
    @classmethod
    def _optional(cls, v: object) -> object:
        return _blank_to_none(v)


class CentresIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    place: str = Field(min_length=2, max_length=80)  # locality name or 6-digit PIN code
    material: WasteCategory | None = None

    @field_validator("place", mode="before")
    @classmethod
    def _clean(cls, v: object) -> str:
        return _one_line(v)

    @field_validator("material", mode="before")
    @classmethod
    def _optional(cls, v: object) -> object:
        return _blank_to_none(v)


# ---------- helpers ----------

def _reply(status_code: int, status: str, say: str, **fields: Any) -> JSONResponse:
    return JSONResponse({"status": status, "say": say, **fields}, status_code=status_code,
                        headers={"Cache-Control": "no-store"})


def _authorised(request: Request) -> JSONResponse | None:
    """None when the request may go ahead, otherwise the refusal to send."""
    settings = get_settings()
    if not settings.voice_tools_ready:
        return _reply(503, "unavailable", "The voice helper isn't switched on yet. Please use the RELOOP website.")
    given = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(given.encode(), settings.voice_tool_secret.strip().encode()):
        log.warning("voice tool call with missing or wrong key")
        return _reply(401, "unauthorised", "This request isn't allowed.")
    return None


async def _parse(request: Request, model: type[BaseModel]) -> BaseModel | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _reply(422, "invalid", "I didn't catch that. Could you say it again?")
    try:
        return model.model_validate(body)
    except ValidationError as e:
        field = str(e.errors()[0]["loc"][0]) if e.errors() and e.errors()[0]["loc"] else "input"
        return _reply(422, "invalid", "I didn't catch that. Could you say it again?", invalid_field=field)


def _limited(request: Request) -> JSONResponse | None:
    message = rate_limiter().check(request, "voice")
    return _reply(429, "busy", message) if message else None


def _sentence(text: str, limit: int = 300) -> str:
    text = _one_line(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "..."


def _first_sentence(text: str, limit: int = 200) -> str:
    """Spoken answers stay short: the first sentence only, capped in length."""
    text = _one_line(text)
    end = text.find(". ")
    return _sentence(text[: end + 1] if end != -1 else text, limit)


def _source_list(answer: Answer) -> list[dict[str, str | None]]:
    seen: list[dict[str, str | None]] = []
    for s in answer.sources:
        entry = {"title": s.title, "publisher": s.publisher, "published_on": s.published_on, "url": s.source_url}
        if entry not in seen:
            seen.append(entry)
    return seen


def _titles(answer: Answer) -> str:
    titles = list(dict.fromkeys(s.title for s in answer.sources))
    return " and ".join(titles[:2])


def _speak_answer(answer: Answer) -> str:
    if answer.mode == AnswerMode.GROUNDED:
        body = " ".join(_one_line(seg.text) for seg in answer.segments if seg.text.strip())
        return f"{_sentence(body, 700)} This comes from {_titles(answer)}."
    if answer.mode == AnswerMode.PASSAGES and answer.sources:
        first = answer.sources[0]
        return f"Here is what {first.title} says: {_sentence(first.content, 350)}"
    if answer.mode == AnswerMode.NO_SOURCE:
        return ("The official documents I have don't cover that, so I can't give you a verified answer. "
                "Please check with your local municipal office.")
    return "I can't check the official documents right now. Please try again in a little while."


# ---------- tools ----------

@router.post("/ask")
async def voice_ask(request: Request) -> JSONResponse:
    if (refusal := _authorised(request)) is not None:
        return refusal
    parsed = await _parse(request, AskIn)
    if isinstance(parsed, JSONResponse):
        return parsed
    assistant = _assistant_override if _assistant_override is not None else get_assistant(get_settings())
    if assistant is None:
        return _reply(503, "unavailable", "The official documents aren't loaded yet, so I can't answer from verified sources.")
    if (busy := _limited(request)) is not None:
        return busy

    answer = assistant.answer(parsed.question)
    log.info("voice ask mode=%s sources=%d", answer.mode, len(answer.sources))
    code = 503 if answer.mode == AnswerMode.UNAVAILABLE else 200
    return _reply(code, answer.mode.value if code == 200 else "unavailable", _speak_answer(answer),
                  sources=_source_list(answer) if answer.mode in (AnswerMode.GROUNDED, AnswerMode.PASSAGES) else [])


def _classify_say(result: PipelineResult) -> tuple[str, list[str]]:
    """What to say, and the questions to put to the caller next."""
    scan = result.scan
    parts: list[str] = [DEMO_PREFIX] if scan.demo else []
    questions: list[str] = []

    if item_unclear(scan):
        questions = scan.clarifying_questions[:2] or ["What is the item, and what is it mostly made of?"]
        parts.append("I'm not sure what the item is yet, so I won't guess. " + questions[0])
        return "".join(parts).strip(), questions

    lane = LANES_BY_CATEGORY[scan.primary_category]
    hedge = "the item is" if scan.certainty == Certainty.CLEAR else "I think the item is"
    item = scan.identified_item.rstrip(".")
    if len(item) > 1 and item[1].islower():  # "Wooden chair" -> "wooden chair", but keep "AA battery"
        item = item[0].lower() + item[1:]
    parts.append(f"From your description, {hedge}: {item}. "
                 f"It goes in the {lane.stencil.lower()} lane: {lane.name.lower()}. ")
    if scan.safety_warnings:
        parts.append(f"Safety first: {_first_sentence(scan.safety_warnings[0])} ")
    parts.append(_first_sentence(scan.action_summary) + " ")

    donation = result.donation
    if donation and donation.status == DonationStatus.NEEDS_CONDITION:
        questions.append(CONDITION_QUESTION)
        parts.append(CONDITION_QUESTION)
    elif donation and donation.status == DonationStatus.ELIGIBLE:
        if donation.partners:
            names = ", ".join(f"{p.name} in {p.locality}" for p in donation.partners[:2])
            parts.append(f"It can be donated. Verified places that accept it include {names}. ")
        else:
            kinds = " or ".join(k.lower() for k in donation.receiver_types[:2])
            parts.append(f"It can be donated, for example to {kinds}. ")
        parts.append("You can list it for free on the RELOOP website, on the Donate page.")
    elif donation and donation.status == DonationStatus.NOT_ELIGIBLE and scan.primary_category in (
            WasteCategory.HAZARDOUS, WasteCategory.MEDICAL):
        parts.append(donation.reason)
    return _one_line("".join(parts)), questions


@router.post("/classify")
async def voice_classify(request: Request, background: BackgroundTasks) -> JSONResponse:
    if (refusal := _authorised(request)) is not None:
        return refusal
    parsed = await _parse(request, ClassifyIn)
    if isinstance(parsed, JSONResponse):
        return parsed
    classifier = _classifier_override if _classifier_override is not None else get_classifier(get_settings())
    if classifier is None:
        return _reply(503, "unavailable", "AI classification isn't switched on yet. Please use the RELOOP website.")
    if (busy := _limited(request)) is not None:
        return busy

    assistant = _assistant_override if _assistant_override is not None else get_assistant(get_settings(), generate=False)
    repo = partner_repo()
    pipeline = WastePipeline(classifier, assistant, DirectoryPartners(repo) if repo else None)
    try:
        result = pipeline.run_description(parsed.description, parsed.condition)
    except ClassifierUnavailable as e:
        return _reply(503, "unavailable", f"{e} You can also scan a photo on the RELOOP website.")

    scan = result.scan
    say, questions = _classify_say(result)
    lane = LANES_BY_CATEGORY[scan.primary_category]
    log.info("voice classify category=%s certainty=%s action=%s donation=%s demo=%s", scan.primary_category,
             scan.certainty, scan.recommended_action, result.donation.status if result.donation else None, scan.demo)
    knowledge = result.knowledge
    if not scan.demo:
        background.add_task(record_usage, "voice", scan.primary_category, "not_given")
    return _reply(
        200, "needs_more_detail" if item_unclear(scan) else "ok", say,
        demo=scan.demo,
        item=scan.identified_item,
        certainty=scan.certainty.value,  # a word, never a percentage
        lane={"category": scan.primary_category.value, "name": lane.name, "where": lane.where},
        possibly_hazardous=scan.possibly_hazardous,
        main_advice=scan.action_summary,
        steps=scan.disposal_steps[:5],
        options=[{"title": o.title, "detail": o.detail} for o in result.options],
        safety_warnings=scan.safety_warnings,
        donation=None if result.donation is None else {
            "status": result.donation.status.value,
            "reason": result.donation.reason,
            "receiver_types": result.donation.receiver_types,
            "verified_partners": [{"name": p.name, "locality": p.locality} for p in result.donation.partners],
        },
        ask_caller=questions,
        condition_used=result.condition.value if result.condition else None,
        official_guidance={
            "found": bool(knowledge and knowledge.mode in (AnswerMode.GROUNDED, AnswerMode.PASSAGES) and knowledge.sources),
            "sources": _source_list(knowledge) if knowledge else [],
        },
    )


@router.post("/centres")
async def voice_centres(request: Request) -> JSONResponse:
    if (refusal := _authorised(request)) is not None:
        return refusal
    parsed = await _parse(request, CentresIn)
    if isinstance(parsed, JSONResponse):
        return parsed
    if (busy := _limited(request)) is not None:
        return busy

    found = partner_service().search(parsed.place, parsed.material)
    verified = found.verified[:3]
    unverified = [] if parsed.material == WasteCategory.MEDICAL else found.unverified[:3]

    parts: list[str] = [found.notices[0] + " "] if parsed.material == WasteCategory.MEDICAL and found.notices else []
    if verified:
        names = "; ".join(f"{e.name}, {e.locality}" for e in verified)
        parts.append(f"I found {len(verified)} place{'s' if len(verified) > 1 else ''} checked by RELOOP: {names}. ")
    else:
        parts.append(f"I don't have a place checked by RELOOP near {parsed.place} yet. ")
    if unverified:
        names = "; ".join(p.name for p in unverified)
        parts.append(f"OpenStreetMap lists {names} nearby, but RELOOP hasn't checked them, so please call ahead first.")
    log.info("voice centres material=%s verified=%d unverified=%d", parsed.material, len(verified), len(unverified))
    return _reply(
        200, "ok" if (verified or unverified) else "none_found", _one_line("".join(parts)),
        verified=[{"name": e.name, "kind": KIND_LABELS[e.kind], "locality": e.locality, "pin_code": e.pin_code,
                   "phone": e.phone, "distance_km": round(e.distance_km, 1) if e.distance_km is not None else None}
                  for e in verified],
        unverified=[{"name": p.name, "kind": p.kind_label, "verified": False,
                     "distance_km": round(p.distance_km, 1) if p.distance_km is not None else None}
                    for p in unverified],
        notices=found.notices,
        attribution=OSM_ATTRIBUTION if unverified else None,
    )
