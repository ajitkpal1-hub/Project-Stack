"""AI waste scanner, driven by the multi-agent workflow (reloop/agents/pipeline.py).

upload -> validate -> Classification -> Knowledge -> Recommendation -> Donation Matching -> Safety Review -> page.
Nothing is stored yet (history arrives with accounts in Phase 6).
"""

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from reloop.config import get_settings
from reloop.models.categories import LANES_BY_CATEGORY
from reloop.agents.pipeline import WastePipeline
from reloop.models.classification import CONDITION_LABELS, Certainty, Condition
from reloop.models.pipeline import DonationStatus, PipelineResult, StepStatus
from reloop.rag.answer import get_assistant
from reloop.routes.deps import partner_repo, rate_limiter
from reloop.services.partners import DirectoryPartners
from reloop.services.classifier import Classifier, ClassifierUnavailable, get_classifier
from reloop.templating import templates
from reloop.utils.images import MAX_UPLOAD_BYTES, ImageValidationError, prepare_image

router = APIRouter()
log = logging.getLogger("reloop.scan")

CERTAINTY_LABELS = {
    Certainty.CLEAR: "Clear",
    Certainty.LIKELY: "Likely",
    Certainty.UNSURE: "Unsure",
}
CERTAINTY_ICONS = {Certainty.CLEAR: "cert-clear", Certainty.LIKELY: "cert-likely", Certainty.UNSURE: "cert-unsure"}

# Let tests swap the classifier and knowledge assistant without touching settings.
_classifier_override = None
_assistant_override = None


def _classifier():
    return _classifier_override if _classifier_override is not None else get_classifier(get_settings())


def _pipeline(classifier: Classifier | None) -> WastePipeline:
    assistant = _assistant_override if _assistant_override is not None else get_assistant(get_settings())
    repo = partner_repo()
    return WastePipeline(classifier, assistant, DirectoryPartners(repo) if repo else None)


def _render(request: Request, status_code: int = 200, **ctx) -> HTMLResponse:
    classifier = _classifier()
    base = {
        "active": "scan",
        "ai_ready": classifier is not None,
        "demo_mode": bool(classifier and classifier.is_demo),
        "lanes_by_category": LANES_BY_CATEGORY,
        "certainty_labels": CERTAINTY_LABELS,
        "certainty_icons": CERTAINTY_ICONS,
        "condition_labels": CONDITION_LABELS,
        "donation_status": DonationStatus,
        "step_status": StepStatus,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }
    return templates.TemplateResponse(request, "scan.html", {**base, **ctx}, status_code=status_code)


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request) -> HTMLResponse:
    return _render(request)


@router.post("/scan", response_class=HTMLResponse)
async def scan_submit(
    request: Request,
    photo: UploadFile | None = File(None),
    note: str = Form(""),
) -> HTMLResponse:
    classifier = _classifier()
    if classifier is None:
        return _render(request, status_code=503, error="AI scanning isn't switched on yet. Please check back soon.")
    if photo is None or not photo.filename:
        return _render(request, status_code=422, error="Please choose a photo of the item first.")

    raw = await photo.read(MAX_UPLOAD_BYTES + 1)
    try:
        image = prepare_image(raw, photo.content_type)
    except ImageValidationError as e:
        return _render(request, status_code=422, error=str(e))

    limited = rate_limiter().check(request, "scan")  # each scan is a paid AI call
    if limited:
        return _render(request, status_code=429, error=limited)

    try:
        outcome = _pipeline(classifier).run(image, note=note.strip() or None, filename=photo.filename)
    except ClassifierUnavailable as e:
        return _render(request, status_code=503, error=str(e))

    log.info("scan category=%s certainty=%s action=%s demo=%s", outcome.scan.primary_category, outcome.scan.certainty,
             outcome.scan.recommended_action, outcome.scan.demo)
    return _render(request, result=outcome.scan, pipeline=outcome)


@router.post("/scan/condition", response_class=HTMLResponse)
async def scan_condition(request: Request, pipeline_json: str = Form(...), condition: str = Form(...)) -> HTMLResponse:
    # The previous result travels in the form. It's validated again here, re-checked by
    # the guardrails and the Safety Review, and a tampered value only changes the sender's own page.
    try:
        previous = PipelineResult.model_validate_json(pipeline_json)
        chosen = Condition(condition)
    except (ValidationError, ValueError):
        return _render(request, status_code=422, error="Something went wrong with that answer. Please scan the item again.")
    outcome = _pipeline(None).rerun_with_condition(previous, chosen)  # no AI call needed
    return _render(request, result=outcome.scan, pipeline=outcome, condition=chosen)
