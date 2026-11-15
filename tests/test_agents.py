"""Phase 5: multi-agent workflow. Every AI and network call is faked."""

import html as html_lib
import re

import pytest
from fastapi.testclient import TestClient

from reloop.agents.donation import DonationMatchingAgent
from reloop.agents.knowledge import KnowledgeAgent, build_question
from reloop.agents.pipeline import WastePipeline
from reloop.agents.recommendation import RecommendationAgent
from reloop.agents.safety import SafetyReviewAgent
from reloop.models.categories import WasteCategory
from reloop.models.classification import Action, Certainty, Component, Condition, ReuseStatus
from reloop.models.knowledge import Answer, AnswerMode, RetrievedChunk
from reloop.models.pipeline import DonationMatch, DonationStatus, Option, Partner, PipelineResult, StepStatus
from reloop.rag.answer import KnowledgeAssistant
from reloop.rag.embeddings import HashEmbedder
from reloop.routes import scan as scan_route
from reloop.services.classifier import ClassifierUnavailable, MockClassifier
from reloop.services.guardrails import apply_guardrails
from reloop.utils.images import prepare_image
from reloop.web import create_app
from tests.test_rag import SETTINGS, CitingGenerator, loaded_store
from tests.test_scan import _ai, make_image, post_photo

MEDICAL = dict(primary_category=WasteCategory.MEDICAL,
               components=[Component(name="strip", material="foil", category=WasteCategory.MEDICAL)])


def scan(**overrides):
    return apply_guardrails(_ai(**overrides))


def image():
    return prepare_image(make_image(), "image/jpeg")


class ExplodingAssistant:
    def answer(self, question):
        raise RuntimeError("boom")


class StubAssistant:
    def __init__(self, answer: Answer):
        self._answer = answer
        self.questions = []

    def answer(self, question):
        self.questions.append(question)
        return self._answer


SOURCE = RetrievedChunk(content="Keep sharps in a puncture-proof box.", similarity=0.8, title="Rules (fixture)")


# ---------- knowledge ----------

def test_knowledge_skips_unclear_items_and_missing_kb():
    stub = StubAssistant(Answer(mode=AnswerMode.NO_SOURCE, question="q"))
    answer, step = KnowledgeAgent(stub).run(scan(certainty=Certainty.UNSURE))
    assert answer is None and step.status == StepStatus.SKIPPED and stub.questions == []
    answer, step = KnowledgeAgent(None).run(scan())
    assert answer is None and step.status == StepStatus.SKIPPED and "isn't available" in step.summary


def test_knowledge_asks_about_the_identified_item():
    stub = StubAssistant(Answer(mode=AnswerMode.GROUNDED, question="q", sources=[SOURCE]))
    answer, step = KnowledgeAgent(stub).run(scan(identified_item="Used syringe", **MEDICAL))
    assert answer.mode == AnswerMode.GROUNDED and step.status == StepStatus.DONE
    assert "Used syringe" in stub.questions[0] and "medical" in stub.questions[0]


def test_knowledge_question_is_trimmed():
    assert len(build_question(scan(identified_item="x" * 1000))) < 250


def test_knowledge_failure_is_contained():
    answer, step = KnowledgeAgent(ExplodingAssistant()).run(scan())
    assert answer is None and step.status == StepStatus.FAILED


def test_knowledge_no_source_is_reported_honestly():
    stub = StubAssistant(Answer(mode=AnswerMode.NO_SOURCE, question="q", message="not found"))
    _, step = KnowledgeAgent(stub).run(scan())
    assert "don't cover" in step.summary


# ---------- recommendation ----------

def test_recommendation_follows_hierarchy_without_duplicates():
    s = scan(primary_category=WasteCategory.E_WASTE, recommended_action=Action.SPECIAL_HANDLING,
             reuse_status=ReuseStatus.NOT_REUSABLE,
             components=[Component(name="phone", material="mixed", category=WasteCategory.E_WASTE)])
    _, options, _ = RecommendationAgent().run(s)
    actions = [o.action for o in options]
    assert actions[0] == Action.SPECIAL_HANDLING
    assert Action.REPAIR in actions and len(actions) == len(set(actions)) <= 3


def test_recommendation_ask_first_offers_nothing_else():
    _, options, _ = RecommendationAgent().run(scan(certainty=Certainty.UNSURE))
    assert [o.action for o in options] == [Action.ASK_FIRST]


@pytest.mark.parametrize("condition,first", [
    (Condition.WORKS_CLEAN, Action.DONATE), (Condition.NEEDS_REPAIR, Action.REPAIR),
    (Condition.BROKEN, Action.RECYCLE), (Condition.NOT_SURE, Action.ASK_FIRST),
])
def test_recommendation_reranks_after_condition(condition, first):
    s, options, step = RecommendationAgent().run(scan(), condition)
    assert options[0].action == first and s.needs_condition_check is False
    assert "after you said" in step.summary


# ---------- donation matching ----------

def test_donation_never_for_medical():
    match, _ = DonationMatchingAgent().run(scan(**MEDICAL))
    assert match.status == DonationStatus.NOT_ELIGIBLE and not match.receiver_types


def test_donation_waits_for_condition():
    match, _ = DonationMatchingAgent().run(scan())
    assert match.status == DonationStatus.NEEDS_CONDITION


def test_donation_eligible_names_kinds_not_organisations():
    s, _, _ = RecommendationAgent().run(scan(primary_category=WasteCategory.TEXTILE), Condition.WORKS_CLEAN)
    match, step = DonationMatchingAgent().run(s)
    assert match.status == DonationStatus.ELIGIBLE
    assert match.receiver_types and match.partners == []
    assert "0 verified partner" in step.summary


def test_donation_uses_verified_directory_only():
    class Directory:
        def find(self, category):
            return [Partner(name="Verified Partner (fixture)", locality="Dombivli East", accepts=["clothes"])]

    s, _, _ = RecommendationAgent().run(scan(), Condition.WORKS_CLEAN)
    match, _ = DonationMatchingAgent(Directory()).run(s)
    assert [p.name for p in match.partners] == ["Verified Partner (fixture)"]


def test_donation_not_applicable_when_unknown():
    match, step = DonationMatchingAgent().run(scan(item_detected=False))
    assert match.status == DonationStatus.NOT_APPLICABLE and step.status == StepStatus.SKIPPED


# ---------- safety review ----------

def test_safety_strips_unsafe_options_and_donation_for_medical():
    s = scan(**MEDICAL)
    s.recommended_action = Action.DONATE  # simulate an earlier agent going wrong
    s.reuse_status = ReuseStatus.POSSIBLY_REUSABLE
    draft = PipelineResult(scan=s, options=[Option(action=Action.DONATE, title="Donate", detail="x"),
                                            Option(action=Action.REUSE, title="Reuse", detail="y")],
                           donation=DonationMatch(status=DonationStatus.ELIGIBLE, reason="x",
                                                  partners=[Partner(name="P", locality="L")]))
    out, step = SafetyReviewAgent().run(draft)
    assert step.status == StepStatus.CHANGED
    assert out.scan.recommended_action == Action.SPECIAL_HANDLING
    assert out.scan.reuse_status == ReuseStatus.NOT_REUSABLE
    assert {o.action for o in out.options} == {Action.SPECIAL_HANDLING}
    assert out.donation.status == DonationStatus.NOT_ELIGIBLE and out.donation.partners == []
    assert any("Never donate" in w for w in out.scan.safety_warnings)


def test_safety_holds_donation_until_condition_confirmed():
    s = scan()
    draft = PipelineResult(scan=s, options=[Option(action=Action.DONATE, title="Donate", detail="x")],
                           donation=DonationMatch(status=DonationStatus.ELIGIBLE, reason="x"))
    out, _ = SafetyReviewAgent().run(draft)
    assert all(o.action != Action.DONATE for o in out.options)
    assert out.donation.status == DonationStatus.NEEDS_CONDITION


def test_safety_unclear_item_only_asks():
    s = scan()
    s.certainty = Certainty.UNSURE
    draft = PipelineResult(scan=s, options=[Option(action=Action.RECYCLE, title="Recycle", detail="x")])
    out, _ = SafetyReviewAgent().run(draft)
    assert out.scan.recommended_action == Action.ASK_FIRST
    assert [o.action for o in out.options] == [Action.ASK_FIRST]


def test_safety_drops_grounded_answer_without_sources():
    draft = PipelineResult(scan=scan(), knowledge=Answer(mode=AnswerMode.GROUNDED, question="q", sources=[]),
                           options=[Option(action=Action.ASK_FIRST, title="t", detail="d")])
    out, _ = SafetyReviewAgent().run(draft)
    assert out.knowledge is None


def test_safety_leaves_safe_results_alone():
    s, options, _ = RecommendationAgent().run(scan(primary_category=WasteCategory.DRY,
                                                   recommended_action=Action.RECYCLE, reuse_status=ReuseStatus.NOT_REUSABLE,
                                                   components=[Component(name="bottle", material="PET", category=WasteCategory.DRY)]))
    donation, _ = DonationMatchingAgent().run(s)
    out, step = SafetyReviewAgent().run(PipelineResult(scan=s, options=options, donation=donation))
    assert step.status == StepStatus.DONE and out.options == options


# ---------- pipeline ----------

def test_pipeline_runs_all_five_agents_in_order():
    result = WastePipeline(MockClassifier()).run(image(), filename="chair.jpg")
    assert [s.agent for s in result.steps] == ["Classification", "Knowledge", "Recommendation", "Donation matching", "Safety review"]
    assert result.scan.demo is True
    assert result.donation.status == DonationStatus.NEEDS_CONDITION


def test_pipeline_survives_knowledge_failure():
    result = WastePipeline(MockClassifier(), ExplodingAssistant()).run(image(), filename="bottle.jpg")
    assert result.steps[1].status == StepStatus.FAILED
    assert result.options and result.steps[-1].agent == "Safety review"


def test_pipeline_without_classifier_is_unavailable():
    with pytest.raises(ClassifierUnavailable):
        WastePipeline(None).run(image())


def test_pipeline_classifier_failure_propagates():
    with pytest.raises(ClassifierUnavailable):
        WastePipeline(MockClassifier(fail=True)).run(image())


def test_rerun_with_condition_makes_no_ai_calls():
    first = WastePipeline(MockClassifier()).run(image(), filename="chair.jpg")
    again = WastePipeline(None, ExplodingAssistant()).rerun_with_condition(first, Condition.WORKS_CLEAN)
    assert again.donation.status == DonationStatus.ELIGIBLE
    assert again.condition == Condition.WORKS_CLEAN


def test_pipeline_with_real_rag_pieces_cites_sources():
    assistant = KnowledgeAssistant(loaded_store(), HashEmbedder(), CitingGenerator(), SETTINGS)
    result = WastePipeline(MockClassifier(), assistant).run(image(), filename="charger.jpg")
    assert result.knowledge is not None
    assert result.knowledge.mode in {AnswerMode.GROUNDED, AnswerMode.NO_SOURCE}


# ---------- scan page ----------

@pytest.fixture
def client():
    yield TestClient(create_app())
    scan_route._classifier_override = None
    scan_route._assistant_override = None


def test_scan_page_shows_agent_trace_and_rules(client):
    scan_route._classifier_override = MockClassifier()
    scan_route._assistant_override = StubAssistant(Answer(mode=AnswerMode.PASSAGES, question="q", sources=[SOURCE],
                                                          message="Here are the most relevant passages."))
    r = post_photo(client, "old-charger.jpg")
    assert r.status_code == 200
    assert "How we worked this out" in r.text and "Safety review" in r.text
    assert "What the official rules say" in r.text and "Rules (fixture)" in r.text
    assert "Your options, best first" in r.text


def test_scan_page_still_works_when_knowledge_fails(client):
    scan_route._classifier_override = MockClassifier()
    scan_route._assistant_override = ExplodingAssistant()
    r = post_photo(client, "bottle.jpg")
    assert r.status_code == 200
    assert "Failed" in r.text and "What the official rules say" not in r.text


def test_condition_round_trip_shows_donation_without_inventing_partners(client):
    scan_route._classifier_override = MockClassifier()
    page = post_photo(client, "chair.jpg").text
    assert "Maybe donatable" in page
    payload = html_lib.unescape(re.search(r'name="pipeline_json" value="([^"]+)"', page).group(1))
    r = client.post("/scan/condition", data={"pipeline_json": payload, "condition": "works_clean"})
    assert r.status_code == 200
    assert "It can be donated" in r.text and "List it for donation" in r.text
    assert "haven't verified any donation partners" in r.text


def test_condition_step_works_with_ai_switched_off(client):
    scan_route._classifier_override = MockClassifier()
    page = post_photo(client, "chair.jpg").text
    payload = html_lib.unescape(re.search(r'name="pipeline_json" value="([^"]+)"', page).group(1))
    scan_route._classifier_override = None  # AI now unconfigured (settings are isolated in tests)
    r = client.post("/scan/condition", data={"pipeline_json": payload, "condition": "broken"})
    assert r.status_code == 200 and "Not for donation" in r.text


def test_medicine_scan_never_shows_donation_or_reuse(client):
    scan_route._classifier_override = MockClassifier()
    r = post_photo(client, "medicine.jpg")
    assert "Not for donation" in r.text
    assert "List it for donation" not in r.text and "It can be donated" not in r.text


def test_known_item_waiting_for_condition_still_gets_guidance_and_donation_check():
    """Claude may answer 'ask first' because it needs the condition, not because the item is unknown."""
    s = scan(primary_category=WasteCategory.TEXTILE, certainty=Certainty.LIKELY, recommended_action=Action.ASK_FIRST,
             components=[Component(name="shirt", material="cotton", category=WasteCategory.TEXTILE)])
    stub = StubAssistant(Answer(mode=AnswerMode.NO_SOURCE, question="q", message="none"))
    _, k_step = KnowledgeAgent(stub).run(s)
    assert k_step.status == StepStatus.DONE and stub.questions
    match, _ = DonationMatchingAgent().run(s)
    assert match.status == DonationStatus.NEEDS_CONDITION
    _, options, _ = RecommendationAgent().run(s)
    assert len(options) > 1  # lane fallbacks shown alongside "tell us more"
