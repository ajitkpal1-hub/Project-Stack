"""AI waste scanner: upload -> validate -> classify -> guardrails -> result.

Nothing is stored in Phase 3 (history arrives with accounts in Phase 6).
"""

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from reloop.config import get_settings
from reloop.models.categories import LANES_BY_CATEGORY
from reloop.models.classification import CONDITION_LABELS, Certainty, Condition, ScanResult
from reloop.services.classifier import ClassifierUnavailable, get_classifier
from reloop.services.guardrails import apply_condition, apply_guardrails
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

# Lets the classifier be swapped in tests without touching settings.
_classifier_override = None


def _classifier():
    return _classifier_override if _classifier_override is not None else get_classifier(get_settings())


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

    try:
        ai = classifier.classify(image, note=note.strip() or None, filename=photo.filename)
    except ClassifierUnavailable as e:
        return _render(request, status_code=503, error=str(e))

    result = apply_guardrails(ai, demo=classifier.is_demo)
    log.info("scan category=%s certainty=%s action=%s demo=%s", result.primary_category, result.certainty, result.recommended_action, result.demo)
    return _render(request, result=result)


@router.post("/scan/condition", response_class=HTMLResponse)
async def scan_condition(request: Request, result_json: str = Form(...), condition: str = Form(...)) -> HTMLResponse:
    # The previous result travels in the form. It's validated again here, and a
    # tampered value only changes the sender's own page.
    try:
        previous = ScanResult.model_validate_json(result_json)
        chosen = Condition(condition)
    except (ValidationError, ValueError):
        return _render(request, status_code=422, error="Something went wrong with that answer. Please scan the item again.")
    previous = apply_guardrails(previous, demo=previous.demo)  # re-check safety on the returned data
    return _render(request, result=apply_condition(previous, chosen), condition=chosen)
