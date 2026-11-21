"""Internal reel-script pipeline. No network: fixture knowledge base, hash embeddings, fake Claude."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from reloop.config import get_settings
from reloop.models.categories import WasteCategory
from reloop.models.content import KeyFact, ReelScriptAI, ReelShot, ReelStatus
from reloop.models.knowledge import RetrievedChunk
from reloop.rag.embeddings import HashEmbedder
from reloop.rag.store import InMemoryStore, StoreError
from reloop.routes import internal as internal_route
from reloop.services import ratelimit
from reloop.services.reels import (
    TOPICS,
    TOPICS_BY_KEY,
    ClaudeReelWriter,
    MockReelWriter,
    ReelWriterError,
    find_passages,
    make_reel,
    pick_topic,
    review_script,
    sheet_row,
)
from reloop.web import create_app
from tests.test_rag import SETTINGS, loaded_store
from tests.test_scan import _response

SECRET = "test-internal-secret-0123456789abcdefghij"  # test value only
KEY = {"X-Reloop-Internal-Key": SECRET}
BATTERIES = TOPICS_BY_KEY["batteries"]
MEDICINES = TOPICS_BY_KEY["medicines"]


def passage(text: str, title: str = "Test Guidance (fixture)") -> RetrievedChunk:
    return RetrievedChunk(content=text, similarity=0.9, title=title)


PASSAGES = [passage("Used household batteries must not be placed in the wet or dry waste bins. "
                    "Keep used batteries in a closed box and hand them over at a battery collection point.")]


def script(**over) -> ReelScriptAI:
    base = dict(
        title="Where do used batteries go?",
        hook="Your old batteries don't belong in either bin",
        hook_on_screen="Not in the bin!",
        shots=[ReelShot(number=n, seconds=s, visual="Hands hold batteries over two bins", on_screen_text="Not here",
                        voiceover=v) for n, s, v in [
                            (1, 4, "Your old batteries don't belong in either bin."),
                            (2, 8, "Used batteries must not go in the wet or dry bin."),
                            (3, 8, "Keep them in a closed box."),
                            (4, 8, "Hand them over at a battery collection point."),
                            (5, 6, "Sort smart.")]],
        caption="Used batteries never go in the wet or dry bin. Keep them in a closed box. Share this with your family.",
        hashtags=["#RELOOP", "WasteSegregation", "#Dombivli", "#reloop", "#Sort Smart"],
        key_facts=[KeyFact(fact="Batteries must not go in the wet or dry bins", source_number=1),
                   KeyFact(fact="Keep used batteries in a closed box", source_number=1)],
        safety_note="Keep batteries away from heat.",
    )
    base.update(over)
    return ReelScriptAI(**base)


# ---------- topics ----------

def test_topic_rotation_covers_every_topic_and_respects_avoid():
    seen = {pick_topic(date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + d)).key for d in range(3 * len(TOPICS))}
    assert seen == set(TOPICS_BY_KEY)
    day = date(2026, 11, 23)
    first = pick_topic(day)
    assert pick_topic(day, {first.key}).key != first.key
    assert pick_topic(day, set(TOPICS_BY_KEY)) in TOPICS  # avoiding everything still returns a topic


def test_find_passages_uses_the_knowledge_base():
    found = find_passages(BATTERIES, loaded_store(), HashEmbedder(), SETTINGS)
    assert found and any("batteries" in p.content.lower() for p in found)
    assert len(found) <= 6


# ---------- the whole pipeline ----------

def test_make_reel_draft_with_demo_writer():
    draft = make_reel(BATTERIES, loaded_store(), HashEmbedder(), MockReelWriter(), SETTINGS)
    assert draft.status == ReelStatus.DRAFT and draft.demo is True
    assert draft.review_notes[0].startswith("DEMONSTRATION DRAFT")
    assert draft.sources and draft.sources[0].title == "Test Guidance (fixture)"
    assert draft.script and draft.script.key_facts


def test_no_sources_means_no_script():
    draft = make_reel(BATTERIES, InMemoryStore(), HashEmbedder(), MockReelWriter(), SETTINGS)
    assert draft.status == ReelStatus.NO_SOURCE and draft.script is None and not draft.sources


def test_writer_returning_no_facts_is_no_source():
    draft = make_reel(BATTERIES, loaded_store(), HashEmbedder(), MockReelWriter(script=script(shots=[], key_facts=[])), SETTINGS)
    assert draft.status == ReelStatus.NO_SOURCE and draft.script is None


# ---------- rules after the model ----------

def test_clean_script_passes_and_is_tidied():
    s, notes, status = review_script(script(), BATTERIES, PASSAGES)
    assert status == ReelStatus.DRAFT and notes == []
    assert s.hashtags == ["#RELOOP", "#WasteSegregation", "#Dombivli", "#SortSmart"]  # prefixed, deduped, no spaces
    assert [x.number for x in s.shots] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("bad, expect", [
    ({"caption": "Recycling one battery saves 2 kg of waste."}, "2 kg"),
    ({"caption": "Sorting cuts 30% of landfill."}, "30%"),
    ({"caption": "It also cuts carbon emissions."}, "carbon"),
    ({"caption": "Learn more at reloop.in today."}, "link or phone"),
    ({"caption": "Call 98765 43210 for pickup."}, "link or phone"),
    ({"caption": "Or donate them to a neighbour who needs them."}, "donating"),
    ({"key_facts": [KeyFact(fact="x", source_number=4)]}, "don't exist"),
])
def test_rules_flag_what_reviewers_must_fix(bad, expect):
    _, notes, status = review_script(script(**bad), BATTERIES, PASSAGES)
    assert status == ReelStatus.NEEDS_FIX
    assert any(expect in n for n in notes), notes


def test_figure_in_sources_is_allowed():
    src = [passage("At least 50% of household waste is wet waste. Keep it separate.")]
    _, notes, status = review_script(script(caption="At least 50% of household waste is wet waste."), BATTERIES, src)
    assert status == ReelStatus.DRAFT, notes


def test_safety_lines_that_say_never_donate_are_fine():
    _, notes, status = review_script(script(caption="Never donate or reuse expired medicines. Hand them over separately."),
                                     MEDICINES, PASSAGES)
    assert status == ReelStatus.DRAFT, notes


def test_donating_is_fine_for_reuse_items():
    _, _, status = review_script(script(caption="If it works and is clean, donate it."), TOPICS_BY_KEY["plastic"], PASSAGES)
    assert status == ReelStatus.DRAFT  # only hazardous and medical topics block donation wording


def test_length_and_hook_warnings_do_not_block():
    long = script(hook="This is a very long hook that keeps going on and on and on forever",
                  shots=script().shots[:2])
    _, notes, status = review_script(long, BATTERIES, PASSAGES)
    assert status == ReelStatus.DRAFT
    assert any("shots" in n for n in notes) and any("hook" in n for n in notes)


def test_sheet_row_shape():
    draft = make_reel(BATTERIES, loaded_store(), HashEmbedder(), MockReelWriter(), SETTINGS)
    row = sheet_row(draft, datetime(2026, 11, 23, 3, 30, tzinfo=timezone.utc))
    assert row["Created (IST)"] == "23/11/2026 09:00"
    assert row["Status"] == "DEMO - Draft - needs review"
    assert row["Shot list"].startswith("1. (4s) SHOW:") and "[1]" in row["Key facts"]
    assert row["Sources"].startswith("[1] Test Guidance (fixture)")
    assert row["Reviewer"] == "" and row["Posted"] == ""
    assert not any(str(v).startswith(("=", "+", "@")) for v in row.values())


# ---------- Claude writer (faked) ----------

def fake_claude(response=None, error=None, seen=None) -> ClaudeReelWriter:
    w = ClaudeReelWriter(api_key="test-key")

    def parse(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        if error:
            raise error
        return response

    w._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    return w


def test_claude_writer_request_shape():
    seen = {}
    out = fake_claude(_response(parsed=script()), seen=seen).write(BATTERIES, PASSAGES)
    assert out == script()
    assert seen["model"] == "claude-opus-5-5" and seen["output_format"] is ReelScriptAI
    assert seen["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["betas"]
    prompt = seen["messages"][0]["content"]
    assert prompt.startswith("Topic: Used batteries") and "[1] Test Guidance (fixture)" in prompt
    assert "Use ONLY facts stated in the numbered passages" in seen["system"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_claude_writer_refusal_and_truncation(stop):
    with pytest.raises(ReelWriterError):
        fake_claude(_response(stop_reason=stop, parsed=None)).write(BATTERIES, PASSAGES)


def test_claude_writer_connection_error():
    import anthropic
    import httpx2

    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    with pytest.raises(ReelWriterError, match="Couldn't reach"):
        fake_claude(error=err).write(BATTERIES, PASSAGES)


# ---------- the internal endpoint ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    get_settings.cache_clear()
    internal_route._writer_override = MockReelWriter()
    internal_route._knowledge_override = (loaded_store(), HashEmbedder())
    monkeypatch.setattr("reloop.services.reels.find_passages",
                        lambda topic, store, emb, settings: find_passages(topic, store, emb, SETTINGS))
    yield TestClient(create_app())
    internal_route._writer_override = internal_route._knowledge_override = None


def test_endpoint_off_without_secret(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_SECRET", raising=False)
    c = TestClient(create_app())
    assert c.post("/api/internal/reel", json={}, headers=KEY).status_code == 503
    assert c.get("/api/health").json()["integrations"]["internal_api"] is False


@pytest.mark.parametrize("headers", [{}, {"X-Reloop-Internal-Key": "wrong"}, {"X-Reloop-Voice-Key": SECRET}])
def test_endpoint_refuses_wrong_key(client, headers):
    assert client.post("/api/internal/reel", json={}, headers=headers).status_code == 401


def test_endpoint_makes_a_draft(client):
    r = client.post("/api/internal/reel", json={"topic": "batteries"}, headers=KEY)
    data = r.json()
    assert r.status_code == 200 and data["status"] == "draft" and data["topic"] == "batteries"
    assert data["sheet_row"]["Topic"] == "Used batteries" and data["sheet_row"]["Hook"]
    assert r.headers["x-robots-tag"].startswith("noindex") and r.headers["cache-control"] == "no-store"


def test_endpoint_picks_a_topic_when_none_given(client):
    data = client.post("/api/internal/reel", json={"avoid": ["batteries"]}, headers=KEY).json()
    assert data["topic"] in TOPICS_BY_KEY and data["topic"] != "batteries"


def test_endpoint_rejects_unknown_topic(client):
    r = client.post("/api/internal/reel", json={"topic": "gold"}, headers=KEY)
    assert r.status_code == 422 and "batteries" in r.json()["topics"]


def test_endpoint_reports_writer_and_store_failures(client):
    internal_route._writer_override = MockReelWriter(fail=True)
    assert client.post("/api/internal/reel", json={"topic": "batteries"}, headers=KEY).status_code == 503

    class Broken(InMemoryStore):
        def search(self, *a, **k):
            raise StoreError("down")

    internal_route._writer_override = MockReelWriter()
    internal_route._knowledge_override = (Broken(), HashEmbedder())
    r = client.post("/api/internal/reel", json={"topic": "batteries"}, headers=KEY)
    assert r.status_code == 503 and "knowledge base" in r.json()["message"]


def test_endpoint_unconfigured_ai(client, monkeypatch):
    internal_route._writer_override = None
    monkeypatch.setattr(internal_route, "get_reel_writer", lambda s: None)
    assert client.post("/api/internal/reel", json={}, headers=KEY).status_code == 503


def test_endpoint_rate_limited(client, monkeypatch):
    monkeypatch.setitem(ratelimit.POLICIES, "internal", ([ratelimit.Limit(1, 3600)], None))
    assert client.post("/api/internal/reel", json={"topic": "batteries"}, headers=KEY).status_code == 200
    assert client.post("/api/internal/reel", json={"topic": "batteries"}, headers=KEY).status_code == 429


def test_not_on_the_website(client):
    for path in ["/", "/talk", "/assistant"]:
        assert "/api/internal" not in client.get(path).text
    assert client.get("/api/internal/reel").status_code == 405
