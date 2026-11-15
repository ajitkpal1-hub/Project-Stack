"""Phase 3: AI waste scanner. All AI calls are mocked, so no API credits are spent."""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reloop.config import Settings
from reloop.models.categories import WasteCategory
from reloop.models.classification import (
    Action,
    AIClassification,
    Certainty,
    Component,
    Condition,
    ReuseStatus,
)
from reloop.routes import scan as scan_route
from reloop.services.classifier import (
    ClassifierUnavailable,
    ClaudeClassifier,
    MockClassifier,
    get_classifier,
)
from reloop.services.guardrails import apply_condition, apply_guardrails
from reloop.utils.images import MAX_UPLOAD_BYTES, ImageValidationError, prepare_image
from reloop.web import create_app


def make_image(fmt: str = "JPEG", size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 60)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def client():
    yield TestClient(create_app())
    scan_route._classifier_override = None


def use(classifier):
    scan_route._classifier_override = classifier


# ---------- image validation ----------

@pytest.mark.parametrize("fmt,ctype", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_accepts_allowed_formats_and_reencodes_to_jpeg(fmt, ctype):
    prepared = prepare_image(make_image(fmt), ctype)
    assert prepared.media_type == "image/jpeg"
    assert prepared.data[:2] == b"\xff\xd8"


def test_downscales_large_images():
    prepared = prepare_image(make_image("PNG", size=(4000, 3000)), "image/png")
    assert max(prepared.width, prepared.height) == 1568


@pytest.mark.parametrize(
    "raw,ctype,message",
    [
        (b"", "image/jpeg", "empty"),
        (b"not an image at all", "image/jpeg", "couldn't read"),
        (b"GIF89a" + b"\x00" * 50, "image/gif", "JPG, PNG or WEBP"),
        (b"%PDF-1.7 fake", "application/pdf", "JPG, PNG or WEBP"),
    ],
)
def test_rejects_invalid_uploads(raw, ctype, message):
    with pytest.raises(ImageValidationError, match=message):
        prepare_image(raw, ctype)


def test_rejects_real_gif_even_with_jpeg_content_type():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="GIF")
    with pytest.raises(ImageValidationError, match="JPG, PNG or WEBP"):
        prepare_image(buf.getvalue(), "image/jpeg")


def test_rejects_oversized_upload():
    with pytest.raises(ImageValidationError, match="4 MB"):
        prepare_image(b"\xff\xd8" + b"0" * MAX_UPLOAD_BYTES, "image/jpeg")


# ---------- guardrails ----------

def _ai(**overrides) -> AIClassification:
    base = dict(
        item_detected=True, identified_item="Thing",
        components=[Component(name="thing", material="wood", category=WasteCategory.REUSE)],
        primary_category=WasteCategory.REUSE, certainty=Certainty.CLEAR, certainty_reason="Visible.",
        reuse_status=ReuseStatus.POSSIBLY_REUSABLE, possibly_hazardous=False,
        recommended_action=Action.DONATE, action_summary="Donate it.",
        safety_warnings=[], disposal_steps=["Step"], clarifying_questions=[],
    )
    base.update(overrides)
    return AIClassification(**base)


def test_medical_is_never_donatable_even_if_ai_says_so():
    r = apply_guardrails(_ai(
        primary_category=WasteCategory.MEDICAL,
        components=[Component(name="strip", material="foil", category=WasteCategory.MEDICAL)],
    ))
    assert r.reuse_status == ReuseStatus.NOT_REUSABLE
    assert r.recommended_action == Action.SPECIAL_HANDLING
    assert r.possibly_hazardous and not r.needs_condition_check
    assert any("Never donate" in w for w in r.safety_warnings)


def test_hidden_hazardous_component_blocks_donation():
    r = apply_guardrails(_ai(components=[
        Component(name="toy", material="plastic", category=WasteCategory.REUSE),
        Component(name="battery", material="lithium", category=WasteCategory.HAZARDOUS),
    ]))
    assert r.recommended_action == Action.SPECIAL_HANDLING
    assert r.reuse_status == ReuseStatus.NOT_REUSABLE


def test_unsure_result_asks_first():
    r = apply_guardrails(_ai(certainty=Certainty.UNSURE, recommended_action=Action.RECYCLE))
    assert r.recommended_action == Action.ASK_FIRST
    assert r.clarifying_questions


def test_no_item_detected_asks_first():
    r = apply_guardrails(_ai(item_detected=False, certainty=Certainty.LIKELY))
    assert r.recommended_action == Action.ASK_FIRST


def test_possibly_reusable_requires_condition_check():
    assert apply_guardrails(_ai()).needs_condition_check is True


@pytest.mark.parametrize(
    "condition,action",
    [(Condition.WORKS_CLEAN, Action.DONATE), (Condition.NEEDS_REPAIR, Action.REPAIR),
     (Condition.BROKEN, Action.RECYCLE), (Condition.NOT_SURE, Action.ASK_FIRST)],
)
def test_condition_updates_recommendation(condition, action):
    r = apply_condition(apply_guardrails(_ai()), condition)
    assert r.recommended_action == action
    assert r.needs_condition_check is False


def test_broken_electronics_go_to_ewaste():
    r = apply_guardrails(_ai(primary_category=WasteCategory.E_WASTE,
                             components=[Component(name="phone", material="mixed", category=WasteCategory.E_WASTE)]))
    assert apply_condition(r, Condition.BROKEN).recommended_action == Action.SPECIAL_HANDLING


# ---------- classifier selection & Claude response handling ----------

def test_no_provider_means_not_configured():
    assert get_classifier(Settings(llm_provider="", llm_api_key="")) is None
    assert get_classifier(Settings(llm_provider="anthropic", llm_api_key="")) is None


def test_mock_provider_is_flagged_demo():
    c = get_classifier(Settings(llm_provider="mock"))
    assert isinstance(c, MockClassifier) and c.is_demo


def _fake_claude(response=None, error=None) -> ClaudeClassifier:
    c = ClaudeClassifier(api_key="test-key")

    def parse(**kwargs):
        assert kwargs["output_format"] is AIClassification
        assert kwargs["model"] == "claude-opus-5-5"
        assert kwargs["messages"][0]["content"][0]["type"] == "image"
        if error:
            raise error
        return response

    c._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    return c


def _response(stop_reason="end_turn", parsed=None):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, model="claude-opus-5-5",
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_claude_classifier_returns_parsed_output():
    img = prepare_image(make_image(), "image/jpeg")
    expected = _ai()
    assert _fake_claude(_response(parsed=expected)).classify(img) == expected


@pytest.mark.parametrize("stop,parsed", [("refusal", None), ("max_tokens", None), ("end_turn", None)])
def test_claude_classifier_handles_refusal_and_truncation(stop, parsed):
    img = prepare_image(make_image(), "image/jpeg")
    with pytest.raises(ClassifierUnavailable):
        _fake_claude(_response(stop_reason=stop, parsed=parsed)).classify(img)


def test_claude_classifier_maps_connection_errors():
    import anthropic
    import httpx2

    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    img = prepare_image(make_image(), "image/jpeg")
    with pytest.raises(ClassifierUnavailable, match="couldn't reach"):
        _fake_claude(error=err).classify(img)


# ---------- routes ----------

def post_photo(client, name="charger.jpg", data=None, ctype="image/jpeg", note=""):
    return client.post("/scan", files={"photo": (name, data if data is not None else make_image(), ctype)}, data={"note": note})


def test_scan_page_says_when_ai_not_configured(client, monkeypatch):
    use(None)
    monkeypatch.setattr(scan_route, "get_classifier", lambda s: None)
    html = client.get("/scan").text
    assert "switched on yet" in html
    assert post_photo(client).status_code == 503


def test_scan_end_to_end_with_mock(client):
    use(MockClassifier())
    r = post_photo(client, "old-charger.jpg")
    assert r.status_code == 200
    assert "Mobile phone charger" in r.text
    assert "Demo mode" in r.text
    assert "E-WASTE" in r.text
    assert "%" not in r.text.split('id="result-title"')[1].split("fineprint")[0]  # no percentages in the result


def test_scan_medicine_never_offers_donation(client):
    use(MockClassifier())
    html = post_photo(client, "medicine.jpg").text
    assert "List it for donation" not in html
    assert "Never donate" in html


def test_scan_invalid_upload_shows_error(client):
    use(MockClassifier())
    r = post_photo(client, "x.jpg", data=b"nope")
    assert r.status_code == 422
    assert "read that file" in r.text


def test_scan_api_failure_shows_friendly_error(client):
    use(MockClassifier(fail=True))
    r = post_photo(client)
    assert r.status_code == 503
    assert "Please try again" in r.text


def test_condition_flow_round_trip(client):
    use(MockClassifier())
    html = post_photo(client, "chair.jpg").text
    assert "what condition is it in" in html
    assert 'class="btn btn-primary" href="/donate"' not in html  # no donate button before condition is confirmed
    import html as html_lib
    import re

    pipeline_json = html_lib.unescape(re.search(r'name="pipeline_json" value="([^"]+)"', html).group(1))
    r = client.post("/scan/condition", data={"pipeline_json": pipeline_json, "condition": "works_clean"})
    assert r.status_code == 200
    assert "List it for donation" in r.text


def test_condition_rejects_tampered_payload(client):
    use(MockClassifier())
    r = client.post("/scan/condition", data={"pipeline_json": '{"bad": true}', "condition": "works_clean"})
    assert r.status_code == 422


def test_tampered_payload_cannot_make_medical_donatable(client):
    use(MockClassifier())
    tampered = apply_guardrails(_ai(primary_category=WasteCategory.MEDICAL,
                                    components=[Component(name="x", material="y", category=WasteCategory.MEDICAL)]))
    tampered.reuse_status = ReuseStatus.POSSIBLY_REUSABLE
    tampered.recommended_action = Action.DONATE
    from reloop.models.pipeline import DonationMatch, DonationStatus, PipelineResult
    payload = PipelineResult(scan=tampered, donation=DonationMatch(status=DonationStatus.ELIGIBLE, reason="x"))
    r = client.post("/scan/condition", data={"pipeline_json": payload.model_dump_json(), "condition": "works_clean"})
    assert "List it for donation" not in r.text


def test_user_text_is_escaped(client):
    use(MockClassifier())
    r = post_photo(client, "<img src=x onerror=alert(1)>.jpg", note="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in r.text
    assert "<img src=x" not in r.text


@pytest.mark.parametrize("raw", ["mock", " mock ", '"mock"', "'MOCK'"])
def test_provider_setting_tolerates_quotes_and_spaces(raw):
    assert isinstance(get_classifier(Settings(llm_provider=raw)), MockClassifier)


def test_health_llm_diagnostics_never_echo_unknown_values(monkeypatch):
    from reloop.config import get_settings

    leaked = "sk-ant-pasted-in-the-wrong-field"
    monkeypatch.setenv("LLM_PROVIDER", leaked)
    get_settings.cache_clear()
    try:
        body = TestClient(create_app()).get("/api/health").text
        assert leaked not in body
        assert "unrecognised" in body
    finally:
        get_settings.cache_clear()
