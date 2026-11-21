"""Voice API for the ElevenLabs agent. No network: mock classifier, fixture knowledge, fake map."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from reloop.agents.pipeline import WastePipeline
from reloop.config import Settings, get_settings
from reloop.database.memory import InMemoryPartnerRepo
from reloop.models.categories import WasteCategory
from reloop.models.classification import AIClassification, Condition
from reloop.models.pipeline import DonationStatus
from reloop.rag.answer import KnowledgeAssistant
from reloop.rag.embeddings import HashEmbedder
from reloop.rag.store import InMemoryStore, StoreError
from reloop.routes import deps
from reloop.routes import voice as voice_route
from reloop.services import ratelimit
from reloop.services.classifier import ClassifierUnavailable, ClaudeClassifier, MockClassifier
from reloop.web import create_app
from tests.test_partners import OSM_PLACE, FakeGeo, pform
from tests.test_rag import SETTINGS, CitingGenerator, loaded_store
from tests.test_scan import _ai, _response

SECRET = "test-voice-secret-0123456789abcdefghij"  # 38 chars, test value only
KEY = {"X-Reloop-Voice-Key": SECRET}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_SECRET", SECRET)
    get_settings.cache_clear()
    voice_route._classifier_override = MockClassifier()
    voice_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    yield TestClient(create_app())
    voice_route._classifier_override = voice_route._assistant_override = None
    deps._partner_repo_override = deps._geo_override = None


def ask(client, question="How do I dispose of used batteries?", headers=KEY):
    return client.post("/api/voice/ask", json={"question": question}, headers=headers)


def classify(client, description, condition=None):
    body = {"description": description}
    if condition is not None:
        body["condition"] = condition
    return client.post("/api/voice/classify", json=body, headers=KEY)


# ---------- switched off / access ----------

def test_off_without_secret(monkeypatch):
    monkeypatch.delenv("VOICE_TOOL_SECRET", raising=False)
    c = TestClient(create_app())
    r = c.post("/api/voice/ask", json={"question": "batteries?"}, headers=KEY)
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    assert c.get("/api/health").json()["integrations"]["voice_tools"] is False


def test_short_secret_keeps_voice_off(monkeypatch):
    monkeypatch.setenv("VOICE_TOOL_SECRET", "short")
    assert Settings().voice_tools_ready is False
    c = TestClient(create_app())
    assert c.post("/api/voice/ask", json={"question": "x"}, headers={"X-Reloop-Voice-Key": "short"}).status_code == 503


def test_health_reports_voice_on(client):
    data = client.get("/api/health").json()
    assert data["integrations"]["voice_tools"] is True
    assert SECRET not in client.get("/api/health").text


@pytest.mark.parametrize("path", ["/api/voice/ask", "/api/voice/classify", "/api/voice/centres"])
@pytest.mark.parametrize("headers", [{}, {"X-Reloop-Voice-Key": "wrong"}, {"X-Reloop-Voice-Key": SECRET + "x"}])
def test_wrong_or_missing_key_refused(client, path, headers):
    r = client.post(path, json={"question": "x", "description": "x", "place": "x"}, headers=headers)
    assert r.status_code == 401 and r.json()["status"] == "unauthorised"


def test_get_not_allowed(client):
    assert client.get("/api/voice/ask", headers=KEY).status_code == 405


# ---------- input validation ----------

@pytest.mark.parametrize("body", [{"question": ""}, {"question": "x" * 501}, {}, {"question": " "}])
def test_ask_rejects_bad_questions(client, body):
    r = client.post("/api/voice/ask", json=body, headers=KEY)
    assert r.status_code == 422 and r.json()["say"]


@pytest.mark.parametrize("raw", [b"not json", b"[1, 2]", b"null"])
def test_rejects_non_object_bodies(client, raw):
    r = client.post("/api/voice/classify", content=raw, headers={**KEY, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["status"] == "invalid"


def test_classify_rejects_unknown_condition(client):
    r = classify(client, "old chair", condition="like new")
    assert r.status_code == 422 and r.json()["invalid_field"] == "condition"


# ---------- ask ----------

def test_ask_grounded_answer_names_its_source(client):
    r = ask(client)
    data = r.json()
    assert r.status_code == 200 and data["status"] == "grounded"
    assert "Test Guidance (fixture)" in data["say"]
    assert data["sources"][0]["title"] == "Test Guidance (fixture)"


def test_ask_says_when_documents_dont_cover_it(client):
    voice_route._assistant_override = KnowledgeAssistant(InMemoryStore(), HashEmbedder(), CitingGenerator(), SETTINGS)
    data = ask(client, "What is the capital of France?").json()
    assert data["status"] == "no_source" and data["sources"] == []
    assert "can't give you a verified answer" in data["say"]


def test_ask_unconfigured_knowledge_base(client, monkeypatch):
    voice_route._assistant_override = None
    monkeypatch.setattr(voice_route, "get_assistant", lambda *a, **k: None)
    r = ask(client)
    assert r.status_code == 503 and "aren't loaded" in r.json()["say"]


def test_ask_store_failure_is_unavailable(client):
    class BrokenStore(InMemoryStore):
        def search(self, *a, **k):
            raise StoreError("The knowledge base can't be reached right now.")

    voice_route._assistant_override = KnowledgeAssistant(BrokenStore(), HashEmbedder(), CitingGenerator(), SETTINGS)
    r = ask(client)
    assert r.status_code == 503 and r.json()["status"] == "unavailable"


def test_ask_without_ai_reads_passage_with_title(client):
    voice_route._assistant_override = KnowledgeAssistant(loaded_store(), HashEmbedder(), None, SETTINGS)
    data = ask(client).json()
    assert data["status"] == "passages" and data["say"].startswith("Here is what Test Guidance (fixture) says:")


# ---------- classify ----------

def test_classify_charger_asks_condition_before_donation(client):
    data = classify(client, "an old phone charger").json()
    assert data["status"] == "ok" and data["lane"]["category"] == "e-waste"
    assert data["demo"] is True and data["say"].startswith("This is a demonstration answer")
    assert data["donation"]["status"] == "needs_condition" and "does it still work" in data["say"]
    assert data["possibly_hazardous"] is True and "Safety first" in data["say"]
    assert data["certainty"] == "clear"
    assert "the item is: mobile phone charger with cable." in data["say"]
    assert "%" not in data["say"]


def test_classify_keeps_acronyms_in_item_names(client):
    voice_route._classifier_override = SimpleNamespace(is_demo=False, describe=lambda d: _ai(identified_item="AA battery"))
    assert "the item is: AA battery." in classify(client, "a used AA battery").json()["say"]


def test_classify_chair_needs_condition_then_donates(client):
    first = classify(client, "a wooden chair").json()
    assert first["donation"]["status"] == "needs_condition"
    assert "does it still work, and is it clean?" in first["say"]
    assert first["ask_caller"] and not any(o["title"] == "Donate it" for o in first["options"])

    second = classify(client, "a wooden chair", condition="works_clean").json()
    assert second["donation"]["status"] == "eligible" and second["condition_used"] == "works_clean"
    assert "Donate page" in second["say"] and second["ask_caller"] == []


def test_classify_names_only_verified_partners(client):
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform(name="Seva Furniture Bank (fixture)", kind="ngo", materials=[WasteCategory.REUSE],
                               donation_categories=["furniture"]))
    deps._partner_repo_override = repo
    data = classify(client, "a wooden chair", condition="works_clean").json()
    names = [p["name"] for p in data["donation"]["verified_partners"]]
    assert all("(fixture)" in n for n in names)  # nothing invented


@pytest.mark.parametrize("condition", [None, "works_clean", "needs_repair"])
def test_classify_medicine_never_donatable(client, condition):
    data = classify(client, "a strip of medicine tablets", condition=condition).json()
    assert data["donation"]["status"] == "not_eligible"
    assert data["possibly_hazardous"] is True
    assert "never be donated" in data["say"].lower()
    assert not any(o["title"] in {"Donate it", "Reuse it at home", "Repair it"} for o in data["options"])


def test_classify_unclear_item_asks_instead_of_guessing(client):
    data = classify(client, "a thing from the cupboard").json()
    assert data["status"] == "needs_more_detail" and data["ask_caller"]
    assert "won't guess" in data["say"]
    assert data["donation"]["status"] == "not_applicable"


def test_classify_unclear_item_with_condition_still_asks(client):
    data = classify(client, "some stuff", condition="works_clean").json()
    assert data["status"] == "needs_more_detail" and data["donation"]["status"] != "eligible"


def test_classify_empty_condition_is_ignored(client):
    assert classify(client, "a wooden chair", condition="").json()["condition_used"] is None


def test_classify_ai_failure(client):
    voice_route._classifier_override = MockClassifier(fail=True)
    r = classify(client, "a wooden chair")
    assert r.status_code == 503 and "website" in r.json()["say"]


def test_classify_ai_not_configured(client, monkeypatch):
    voice_route._classifier_override = None
    monkeypatch.setattr(voice_route, "get_classifier", lambda s: None)
    assert classify(client, "a wooden chair").status_code == 503


def test_classify_includes_official_guidance_sources(client):
    data = classify(client, "a wooden chair").json()
    assert set(data["official_guidance"]) == {"found", "sources"}


def test_callers_words_are_not_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    classify(client, "my neighbour Sunita's broken chair at flat 12B")
    ask(client, "Flat 12B batteries question")
    assert "12B" not in caplog.text and "Sunita" not in caplog.text


# ---------- centres ----------

def test_centres_verified_first_and_map_labelled(client):
    repo = InMemoryPartnerRepo()
    repo.insert_verified(pform())
    deps._partner_repo_override, deps._geo_override = repo, FakeGeo([OSM_PLACE])
    data = client.post("/api/voice/centres", json={"place": "421201", "material": "e-waste"}, headers=KEY).json()
    assert data["verified"][0]["name"] == "Green E-Waste Collectors (fixture)"
    assert data["say"].index("checked by RELOOP") < data["say"].index("OpenStreetMap")
    assert "hasn't checked them" in data["say"]
    assert all(p["verified"] is False for p in data["unverified"])
    assert data["attribution"].startswith("Map data from OpenStreetMap")


def test_centres_medical_never_lists_map_places(client):
    deps._partner_repo_override, deps._geo_override = InMemoryPartnerRepo(), FakeGeo([OSM_PLACE])
    data = client.post("/api/voice/centres", json={"place": "Dombivli", "material": "medical"}, headers=KEY).json()
    assert data["unverified"] == [] and "biomedical" in data["say"]


def test_centres_none_found_is_honest(client):
    deps._partner_repo_override, deps._geo_override = InMemoryPartnerRepo(), FakeGeo([])
    data = client.post("/api/voice/centres", json={"place": "Thakurli"}, headers=KEY).json()
    assert data["status"] == "none_found" and "don't have a place checked by RELOOP" in data["say"]


def test_centres_rejects_unknown_material(client):
    r = client.post("/api/voice/centres", json={"place": "Kalyan", "material": "gold"}, headers=KEY)
    assert r.status_code == 422


# ---------- usage limits ----------

def test_voice_rate_limited(client, monkeypatch):
    monkeypatch.setitem(ratelimit.POLICIES, "voice", ([ratelimit.Limit(2, 3600)], None))
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    r = ask(client)
    assert r.status_code == 429 and r.json()["status"] == "busy"


def test_refused_requests_do_not_use_up_the_limit(client, monkeypatch):
    monkeypatch.setitem(ratelimit.POLICIES, "voice", ([ratelimit.Limit(1, 3600)], None))
    for _ in range(3):
        ask(client, headers={"X-Reloop-Voice-Key": "wrong"})
        client.post("/api/voice/ask", json={}, headers=KEY)
    assert ask(client).status_code == 200


# ---------- classifier and pipeline from a description ----------

def test_claude_describe_sends_text_only():
    c = ClaudeClassifier(api_key="test-key")
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return _response(parsed=_ai())

    c._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    assert c.describe("an old   steel\ntiffin box") == _ai()
    content = seen["messages"][0]["content"]
    assert [b["type"] for b in content] == ["text"]
    assert "There is no photo" in content[0]["text"] and content[0]["text"].endswith("an old steel tiffin box")
    assert seen["output_format"] is AIClassification


def test_claude_describe_refusal_message():
    c = ClaudeClassifier(api_key="test-key")
    c._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=lambda **k: _response("refusal"))))
    with pytest.raises(ClassifierUnavailable, match="describe it differently"):
        c.describe("something")


def test_pipeline_run_description_applies_safety_review():
    result = WastePipeline(MockClassifier()).run_description("medicine strip", Condition.WORKS_CLEAN)
    assert result.donation.status == DonationStatus.NOT_ELIGIBLE
    assert result.steps[-1].agent == "Safety review"
    assert "your description" not in result.steps[0].summary  # demo results say they're samples


def test_pipeline_run_description_without_classifier():
    with pytest.raises(ClassifierUnavailable):
        WastePipeline(None).run_description("chair")


# ---------- /talk page (ElevenLabs widget) ----------

AGENT = "agent_1101m7n723ahf1q9e8mht5s1cmww"


def test_talk_page_loads_pinned_widget_with_integrity(client):
    r = client.get("/talk")
    assert r.status_code == 200
    assert f'agent-id="{AGENT}"' in r.text
    assert 'src="https://unpkg.com/@elevenlabs/convai-widget-embed@0.24.1/dist/index.js"' in r.text
    assert 'integrity="sha384-' in r.text and 'crossorigin="anonymous"' in r.text
    assert "ElevenLabs" in r.text and "112" in r.text  # privacy and emergency notes


def test_talk_page_widens_policy_only_as_needed(client):
    h = client.get("/talk").headers
    csp = h["content-security-policy"]
    assert "https://unpkg.com/@elevenlabs/convai-widget-embed@0.24.1/dist/index.js" in csp
    assert "wss://api.us.elevenlabs.io" in csp
    assert "unpkg.com/ " not in csp and "https://unpkg.com;" not in csp  # the exact file, never all of unpkg
    assert "openfpcdn" not in csp and "fonts.googleapis" not in csp  # telemetry and Google Fonts stay blocked
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "microphone=(self)" in h["permissions-policy"]


@pytest.mark.parametrize("path", ["/", "/scan", "/assistant", "/centres"])
def test_other_pages_keep_strict_policy(client, path):
    h = client.get(path).headers
    assert "script-src 'self';" in h["content-security-policy"]
    assert "connect-src 'none'" in h["content-security-policy"]
    assert "microphone=()" in h["permissions-policy"]
    assert "elevenlabs" not in client.get(path).text.split("<footer")[0].lower()


@pytest.mark.parametrize("bad", ["", "agent_x", 'agent_abc123abc123abc123" onload="alert(1)', "AGENT_ABCDEFGHIJKLMNOPQRST"])
def test_talk_page_off_without_valid_agent(monkeypatch, bad):
    monkeypatch.setenv("ELEVENLABS_AGENT_ID", bad)
    get_settings.cache_clear()
    r = TestClient(create_app()).get("/talk")
    assert r.status_code == 200
    assert "isn&#39;t switched on" in r.text or "isn't switched on" in r.text
    assert "<elevenlabs-convai" not in r.text and "unpkg" not in r.text
    assert "microphone=()" in r.headers["permissions-policy"]


def test_talk_in_navigation(client):
    assert 'href="/talk"' in client.get("/").text
    assert client.get("/api/health").json()["integrations"]["voice_widget"] is True
