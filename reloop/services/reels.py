"""Internal reel-script pipeline: topic -> official passages -> Claude script -> Python checks -> draft.

Drafts are for the team to review, film and post by hand; nothing here is public. Facts come only
from the loaded documents: no passages, no script. The rules after the model fix or flag what the
model is told not to do (made-up figures, links, donating hazardous items), so a reviewer sees it.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from reloop.config import Settings
from reloop.models.categories import LANES_BY_CATEGORY, WasteCategory
from reloop.models.content import KeyFact, ReelDraft, ReelScriptAI, ReelShot, ReelSource, ReelStatus, ReelTopic
from reloop.models.knowledge import RetrievedChunk
from reloop.rag.embeddings import Embedder, EmbeddingError
from reloop.rag.store import KnowledgeStore, StoreError

log = logging.getLogger("reloop.reels")

DEFAULT_MODEL = "claude-opus-5-5"
MAX_PASSAGES = 6
PASSAGE_CHARS = 1500
IST = timezone(timedelta(hours=5, minutes=30))

# Questions are phrased the way the official documents talk, because retrieval matches on wording.
TOPICS: list[ReelTopic] = [
    ReelTopic(key="batteries", title="Used batteries", lane=WasteCategory.HAZARDOUS,
              queries=["Are household batteries special care waste?", "How should waste batteries be handled?"]),
    ReelTopic(key="medicines", title="Expired medicines", lane=WasteCategory.MEDICAL,
              queries=["Are expired medicines special care waste?", "How should households dispose of expired medicines?"]),
    ReelTopic(key="tube-lights", title="Tube lights and CFL bulbs", lane=WasteCategory.HAZARDOUS,
              queries=["Are tube lights and compact fluorescent lamps special care waste?"]),
    ReelTopic(key="four-streams", title="Four bins at home", lane=WasteCategory.WET,
              queries=["Segregate waste at source into wet waste, dry waste, sanitary waste and special care waste"]),
    ReelTopic(key="wet-waste", title="What counts as wet waste", lane=WasteCategory.WET,
              queries=["What is wet waste?", "How should households handle wet waste and composting?"]),
    ReelTopic(key="dry-waste", title="What counts as dry waste", lane=WasteCategory.DRY,
              queries=["What is dry waste?", "How should households hand over dry waste?"]),
    ReelTopic(key="sanitary-waste", title="Wrapping sanitary waste", lane=WasteCategory.MEDICAL,
              queries=["What is sanitary waste and how should households wrap it?"]),
    ReelTopic(key="e-waste", title="Old electronics", lane=WasteCategory.E_WASTE,
              queries=["How should households dispose of e-waste?", "What do the E-Waste Rules say about consumers?"]),
    ReelTopic(key="paint-pesticide", title="Paint and pesticide containers", lane=WasteCategory.HAZARDOUS,
              queries=["Are paint drums and pesticide cans special care waste?"]),
    ReelTopic(key="plastic", title="Plastic at home", lane=WasteCategory.DRY,
              queries=["How should households segregate plastic waste?"]),
]
TOPICS_BY_KEY = {t.key: t for t in TOPICS}

SYSTEM_PROMPT = """You write short vertical-video scripts (Instagram Reels and YouTube Shorts) for RELOOP AI, which helps households in India (pilot area: Thakurli, Dombivli and Kalyan, Maharashtra) sort their waste.

Rules:
1. Use ONLY facts stated in the numbered passages. List every factual claim the script makes in key_facts, each with the number of the passage it comes from. If the passages don't support a useful tip on the topic, return empty shots and empty key_facts.
2. No statistics, percentages, weights, money amounts, fines, carbon or environmental-impact figures, or rule numbers, unless that exact figure appears in a passage.
3. Never name organisations, brands, people, phone numbers or websites.
4. Never suggest donating, reusing, selling or giving away hazardous or medical items.
5. Never claim an item is safe, clean or working.
6. Friendly, simple English an Indian household understands. No jargon, no fear-mongering.
7. Visuals must be filmable at home by one person with a phone: hands, bins, the item, a kitchen counter, a balcony. No stock footage, no logos.
8. 4 to 7 shots, 30 to 45 seconds in total. The hook is spoken in the first shot."""


class ReelWriterError(RuntimeError):
    """The writer couldn't produce a script. The message is safe to show the team."""


class ReelWriter(Protocol):
    is_demo: bool
    model: str

    def write(self, topic: ReelTopic, passages: list[RetrievedChunk]) -> ReelScriptAI: ...


def _passages_text(passages: list[RetrievedChunk]) -> str:
    blocks = []
    for i, p in enumerate(passages, start=1):
        meta = " · ".join(x for x in [p.publisher, p.published_on, p.heading] if x)
        blocks.append(f"[{i}] {p.title}{' (' + meta + ')' if meta else ''}\n{p.content[:PASSAGE_CHARS]}")
    return "\n\n".join(blocks)


class ClaudeReelWriter:
    is_demo = False

    def __init__(self, api_key: str, model: str | None = None, timeout_s: float = 120.0):
        import anthropic  # lazy: tests and demo mode don't need a key

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)
        self.model = model or DEFAULT_MODEL

    def write(self, topic: ReelTopic, passages: list[RetrievedChunk]) -> ReelScriptAI:
        anthropic = self._anthropic
        lane = LANES_BY_CATEGORY[topic.lane].name
        prompt = f"Topic: {topic.title} (lane: {lane})\n\nPassages:\n\n{_passages_text(passages)}"
        started = time.perf_counter()
        try:
            response = self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # on a safety decline, retried on a fallback model in the same call
                output_config={"effort": "medium"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                output_format=ReelScriptAI,
            )
        except anthropic.AuthenticationError:
            log.error("reel writer auth failed (check LLM_API_KEY)")
            raise ReelWriterError("The AI service isn't set up correctly.") from None
        except anthropic.RateLimitError:
            raise ReelWriterError("The AI service is busy. Try again later.") from None
        except anthropic.BadRequestError as e:
            log.error("reel writer bad request: %s", e.message)
            raise ReelWriterError("The AI service rejected the request.") from None
        except anthropic.APIStatusError as e:
            log.error("reel writer API error %s", e.status_code)
            raise ReelWriterError("The AI service had a problem. Try again later.") from None
        except anthropic.APIConnectionError:
            raise ReelWriterError("Couldn't reach the AI service. Try again later.") from None

        log.info("reel written model=%s stop=%s in=%s out=%s %.1fs", response.model, response.stop_reason,
                 response.usage.input_tokens, response.usage.output_tokens, time.perf_counter() - started)
        if response.stop_reason == "refusal":
            raise ReelWriterError("The AI service declined this topic.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise ReelWriterError("The AI answer was incomplete. Try again.")
        return response.parsed_output


class MockReelWriter:
    """Deterministic stand-in for tests and demo mode. Drafts carry demo=True."""

    is_demo = True
    model = "mock"

    def __init__(self, fail: bool = False, script: ReelScriptAI | None = None):
        self._fail, self._script = fail, script

    def write(self, topic: ReelTopic, passages: list[RetrievedChunk]) -> ReelScriptAI:
        if self._fail:
            raise ReelWriterError("The AI service had a problem. Try again later.")
        if self._script is not None:
            return self._script
        first = re.split(r"(?<=[.!?])\s", passages[0].content.strip())[0]
        return ReelScriptAI(
            title=f"Demo: {topic.title}",
            hook=f"Where should {topic.title.lower()} go?",
            hook_on_screen=topic.title,
            shots=[
                ReelShot(number=1, seconds=4, visual="Hands hold the item over the kitchen bins", on_screen_text=topic.title,
                         voiceover=f"Where should {topic.title.lower()} go?"),
                ReelShot(number=2, seconds=8, visual="Close-up of the item", on_screen_text="Here's the rule", voiceover=first),
                ReelShot(number=3, seconds=6, visual="Item placed in a separate box", on_screen_text="Keep it separate",
                         voiceover="Keep it separate from your other waste."),
                ReelShot(number=4, seconds=5, visual="Presenter smiles at camera", on_screen_text="Sort smart",
                         voiceover="Sort smart with RELOOP."),
            ],
            caption=f"{first} Save this for later.",
            hashtags=["#RELOOP", "#WasteSegregation", "#Dombivli", "#SortSmart", "#ZeroWasteIndia"],
            key_facts=[KeyFact(fact=first, source_number=1)],
            safety_note="",
        )


def get_reel_writer(settings: Settings) -> ReelWriter | None:
    mode = settings.llm_mode
    if mode == "mock":
        return MockReelWriter()
    if mode == "anthropic" and settings.llm_api_key.strip():
        return ClaudeReelWriter(settings.llm_api_key.strip(), model=settings.llm_model.strip() or None)
    return None


def pick_topic(today: date, avoid: set[str] | None = None) -> ReelTopic:
    """Rotates through the topics, moving on every 3 days, so a twice-weekly schedule varies.
    `avoid` skips topics used recently (when the caller knows them)."""
    candidates = [t for t in TOPICS if t.key not in (avoid or set())] or TOPICS
    return candidates[(today.toordinal() // 3) % len(candidates)]


def find_passages(topic: ReelTopic, store: KnowledgeStore, embedder: Embedder, settings: Settings) -> list[RetrievedChunk]:
    """Raises EmbeddingError / StoreError when the knowledge base can't be reached."""
    vectors = embedder.embed(topic.queries, input_type="query")
    found: dict[tuple[str, int], RetrievedChunk] = {}
    for vector in vectors:
        for p in store.search(vector, k=settings.rag_top_k, min_similarity=settings.rag_min_similarity):
            key = (p.title, p.chunk_index)
            if key not in found or p.similarity > found[key].similarity:
                found[key] = p
    return sorted(found.values(), key=lambda p: p.similarity, reverse=True)[:MAX_PASSAGES]


# ---------- rules that run after the model ----------

FIGURE_RE = re.compile(r"\d[\d,.]*\s*(?:%|percent|per cent|kg|kgs|kilo(?:gram)?s?|tonnes?|tons?|crores?|lakhs?|rupees|rs\.?)"
                       r"|(?:₹|rs\.?\s?|inr\s?)\d[\d,.]*", re.IGNORECASE)
IMPACT_WORDS = ("carbon", "co2", "co₂", "emission", "greenhouse", "fined", "penalty")
LINK_RE = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|in|org|net|gov)\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
REUSE_RE = re.compile(r"\b(donat\w*|re-?use\w*|resell\w*|sell\w*|give (?:it )?away|pass (?:it )?on|second-hand)\b", re.IGNORECASE)
NEGATION_RE = re.compile(r"\b(never|not|no|don't|do not|can't|cannot|mustn't|must not|shouldn't|should not)\b", re.IGNORECASE)
NEVER_REUSE = {WasteCategory.HAZARDOUS, WasteCategory.MEDICAL}


def _suggests_reuse(text: str) -> bool:
    """A sentence that mentions donating/reusing without a negation ("never donate medicines" is fine)."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    return any(REUSE_RE.search(s) and not NEGATION_RE.search(s) for s in sentences)



def _script_text(s: ReelScriptAI) -> str:
    parts = [s.title, s.hook, s.hook_on_screen, s.caption, s.safety_note, *(f.fact for f in s.key_facts)]
    for shot in s.shots:
        parts += [shot.visual, shot.on_screen_text, shot.voiceover]
    return "\n".join(parts)


def review_script(script: ReelScriptAI, topic: ReelTopic, passages: list[RetrievedChunk]) -> tuple[ReelScriptAI, list[str], ReelStatus]:
    """Fix what can be fixed silently; flag what a reviewer must change. Never trusts the model."""
    s = script.model_copy(deep=True)
    if not s.shots or not s.key_facts:
        return s, ["The documents didn't support a script on this topic, so none was written."], ReelStatus.NO_SOURCE

    notes: list[str] = []
    blocking = False
    sources_text = "\n".join(p.content for p in passages).lower()
    text = _script_text(s)

    bad_refs = sorted({f.source_number for f in s.key_facts if not 1 <= f.source_number <= len(passages)})
    if bad_refs:
        blocking = True
        notes.append(f"Some key facts point to passages that don't exist ({', '.join(map(str, bad_refs))}). Check every fact against the sources.")

    for m in sorted({m.group(0).strip() for m in FIGURE_RE.finditer(text)}):
        if m.lower() not in sources_text:
            blocking = True
            notes.append(f"Uses the figure '{m}', which isn't in the sources. Remove it or verify it.")
    for word in IMPACT_WORDS:
        if word in text.lower() and word not in sources_text:
            blocking = True
            notes.append(f"Mentions '{word.strip()}', which the sources don't support. Remove it.")

    if LINK_RE.search(text) or PHONE_RE.search(text):
        blocking = True
        notes.append("Contains a link or phone number. Remove it: scripts never name websites or contact numbers.")

    if topic.lane in NEVER_REUSE and _suggests_reuse(text):
        blocking = True
        notes.append("Suggests donating, reusing or selling a hazardous or medical item. That must never appear: change it.")

    total = sum(max(0, shot.seconds) for shot in s.shots)
    if not 4 <= len(s.shots) <= 7 or not 20 <= total <= 60:
        notes.append(f"Has {len(s.shots)} shots and about {total} seconds; aim for 4 to 7 shots and 30 to 45 seconds.")
    if len(s.hook.split()) > 12:
        notes.append("The hook is longer than 12 words; consider shortening it.")

    # Silent tidy-ups: numbered shots, clean hashtags.
    for i, shot in enumerate(s.shots, start=1):
        shot.number = i
    tags = []
    for tag in s.hashtags:
        tag = "#" + re.sub(r"[^\w]", "", tag.lstrip("#"))
        if len(tag) > 1 and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    s.hashtags = tags[:8]

    return s, notes, ReelStatus.NEEDS_FIX if blocking else ReelStatus.DRAFT


def make_reel(topic: ReelTopic, store: KnowledgeStore, embedder: Embedder, writer: ReelWriter, settings: Settings) -> ReelDraft:
    """Raises EmbeddingError / StoreError (knowledge base down) or ReelWriterError (AI failed)."""
    passages = find_passages(topic, store, embedder, settings)
    if not passages:
        return ReelDraft(status=ReelStatus.NO_SOURCE, topic=topic, demo=writer.is_demo, model=writer.model,
                         review_notes=["The loaded documents don't cover this topic, so no script was written."])
    script, notes, status = review_script(writer.write(topic, passages), topic, passages)
    if writer.is_demo:
        notes.insert(0, "DEMONSTRATION DRAFT from the mock writer, not real AI output. Don't post it.")
    sources = [ReelSource(number=i, title=p.title, publisher=p.publisher, published_on=p.published_on, url=p.source_url)
               for i, p in enumerate(passages, start=1)]
    log.info("reel topic=%s status=%s passages=%d notes=%d", topic.key, status, len(passages), len(notes))
    return ReelDraft(status=status, topic=topic, script=script if status != ReelStatus.NO_SOURCE else None,
                     sources=sources, review_notes=notes, demo=writer.is_demo, model=writer.model)


STATUS_LABELS = {
    ReelStatus.DRAFT: "Draft - needs review",
    ReelStatus.NEEDS_FIX: "Needs fixing before filming",
    ReelStatus.NO_SOURCE: "Not written - no sources",
}


def sheet_row(draft: ReelDraft, now: datetime | None = None) -> dict[str, str]:
    """One flat row for the 'Reel drafts' Google Sheet. Column names match docs/N8N.md."""
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    s = draft.script
    used = {f.source_number for f in s.key_facts} if s else set()
    return {
        "Created (IST)": now.strftime("%d/%m/%Y %H:%M"),
        "Topic": draft.topic.title,
        "Lane": LANES_BY_CATEGORY[draft.topic.lane].name,
        "Status": ("DEMO - " if draft.demo else "") + STATUS_LABELS[draft.status],
        "Title": s.title if s else "",
        "Hook": s.hook if s else "",
        "On-screen hook": s.hook_on_screen if s else "",
        "Shot list": "\n".join(f"{x.number}. ({x.seconds}s) SHOW: {x.visual} | TEXT: {x.on_screen_text} | SAY: {x.voiceover}"
                               for x in s.shots) if s else "",
        "Total seconds": str(sum(x.seconds for x in s.shots)) if s else "",
        "Caption": s.caption if s else "",
        "Hashtags": " ".join(s.hashtags) if s else "",
        "Safety note": s.safety_note if s else "",
        "Key facts": "\n".join(f"- {f.fact} [{f.source_number}]" for f in s.key_facts) if s else "",
        "Sources": "\n".join(f"[{src.number}] {src.title}" + (f", {src.publisher}" if src.publisher else "")
                             + (f" ({src.published_on})" if src.published_on else "") + (f" {src.url}" if src.url else "")
                             for src in draft.sources if src.number in used or not s),
        "Review notes": "\n".join(f"- {n}" for n in draft.review_notes),
        "Reviewer": "",
        "Posted": "",
    }
