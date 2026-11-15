"""Donations: list an item, browse and request, the donor's dashboard, and the admin queue.

Routes stay thin: validate the form, call DonationService (which checks permission),
then render or redirect with a one-time message.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from reloop.database.supabase import SupabaseError
from reloop.models.categories import WasteCategory
from reloop.models.donations import (
    CATEGORY_FROM_LANE,
    CATEGORY_LABELS,
    CONDITION_LABELS,
    REQUEST_LABELS,
    STATUS_LABELS,
    DonationCategory,
    ListingCondition,
    ListingForm,
    ListingStatus,
    RequestStatus,
)
from reloop.routes.account import _first_error
from reloop.routes.deps import accounts_ready, donation_service, login_url, require_user, viewer
from reloop.security import flash, verify_csrf
from reloop.services.donations import DonationError
from reloop.templating import templates
from reloop.utils.images import MAX_UPLOAD_BYTES, ImageValidationError, prepare_image

router = APIRouter()
log = logging.getLogger("reloop.donations.routes")

COMMON = {
    "category_labels": CATEGORY_LABELS,
    "condition_labels": CONDITION_LABELS,
    "status_labels": STATUS_LABELS,
    "request_labels": REQUEST_LABELS,
    "statuses": ListingStatus,
    "request_statuses": RequestStatus,
    "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
}


def _render(request: Request, template: str, active: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, template, {**COMMON, "active": active, "ready": accounts_ready(), **ctx}, status_code=status_code)


def _back(request: Request, to: str, message: str, kind: str = "ok") -> RedirectResponse:
    flash(request, message, kind)
    return RedirectResponse(to, status_code=303)


# ---------- donate ----------

@router.get("/donate", response_class=HTMLResponse)
def donate_page(request: Request, title: str = "", lane: str = "", condition: str = "") -> HTMLResponse:
    v = viewer(request)
    prefill: dict = {"title": " ".join(title.split())[:80]}
    try:
        category = CATEGORY_FROM_LANE.get(WasteCategory(lane))
    except ValueError:
        category = None
    if lane in {WasteCategory.HAZARDOUS.value, WasteCategory.MEDICAL.value}:
        return _render(request, "donate.html", "donate", 422, viewer=v, form={},
                       error="Hazardous and medical items can never be listed as donations.")
    if category:
        prefill["category"] = category.value
    if condition in {c.value for c in ListingCondition}:
        prefill["condition"] = condition
    profile = None
    service = donation_service()
    if v.signed_in and service:
        try:
            profile = service.repo.get_profile(v.user.id)
        except SupabaseError:
            profile = None
    if profile:
        prefill.setdefault("locality", profile.locality)
        prefill.setdefault("pin_code", profile.pin_code)
    return _render(request, "donate.html", "donate", viewer=v, form=prefill, from_scan=bool(title or lane),
                   login_link=login_url(str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")))


@router.post("/donate", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
async def donate_submit(request: Request, v=Depends(require_user), title: str = Form(""), category: str = Form(""),
                        condition: str = Form(""), description: str = Form(""), locality: str = Form(""),
                        pin_code: str = Form(""), photo: UploadFile | None = File(None)) -> Response:
    raw = {"title": title, "category": category, "condition": condition, "description": description,
           "locality": locality, "pin_code": pin_code}
    service = donation_service()
    if service is None:
        return _render(request, "donate.html", "donate", 503, viewer=v, form=raw)
    try:
        form = ListingForm(**raw)
    except ValidationError as e:
        return _render(request, "donate.html", "donate", 422, viewer=v, form=raw, error=_first_error(e))

    image = None
    if photo is not None and photo.filename:
        data = await photo.read(MAX_UPLOAD_BYTES + 1)
        try:
            image = prepare_image(data, photo.content_type)  # re-encoded JPEG: hidden location data is dropped
        except ImageValidationError as e:
            return _render(request, "donate.html", "donate", 422, viewer=v, form=raw, error=str(e))
    try:
        service.create_listing(v.user, v.token, form, image)
    except DonationError as e:
        return _render(request, "donate.html", "donate", 422, viewer=v, form=raw, error=str(e), blocked=True)
    except SupabaseError as e:
        return _render(request, "donate.html", "donate", 503, viewer=v, form=raw, error=str(e))
    return _back(request, "/dashboard", "Thanks! Your listing is waiting for a quick review. We'll show it publicly once it's approved.")


# ---------- explore ----------

@router.get("/donations", response_class=HTMLResponse)
def explore(request: Request, category: str = "", place: str = "") -> HTMLResponse:
    place = " ".join(place.split())[:60]
    category = category if category in {c.value for c in DonationCategory} else ""
    service = donation_service()
    listings, error = [], None
    if service:
        try:
            listings = service.browse(category or None, place or None)
        except SupabaseError as e:
            error = str(e)
    return _render(request, "donations.html", "donations", viewer=viewer(request), listings=listings,
                   category=category, place=place, error=error)


@router.get("/donations/{listing_id}", response_class=HTMLResponse)
def listing_page(request: Request, listing_id: str) -> HTMLResponse:
    v = viewer(request)
    service = donation_service()
    view = existing = None
    if service:
        try:
            view = service.view_listing(listing_id, v.user)
            if view and v.signed_in:
                existing = service.existing_request(v.user, v.token, view.listing.id)
        except SupabaseError as e:
            return _render(request, "listing.html", "donations", 503, viewer=v, view=None, error=str(e))
    if view is None:
        return _render(request, "listing.html", "donations", 404, viewer=v, view=None)
    return _render(request, "listing.html", "donations", viewer=v, view=view, existing=existing,
                   login_link=login_url(request.url.path))


@router.post("/donations/{listing_id}/request", dependencies=[Depends(verify_csrf)])
def request_item(request: Request, listing_id: str, v=Depends(require_user), message: str = Form("")) -> Response:
    try:
        donation_service().request_item(v.user, v.token, listing_id, message)
    except (DonationError, SupabaseError) as e:
        return _back(request, f"/donations/{listing_id}", str(e), "error")
    return _back(request, "/dashboard", "Request sent. The donor will approve or decline it, and you'll see the answer here.")


# ---------- dashboard ----------

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, v=Depends(require_user)) -> HTMLResponse:
    service = donation_service()
    if service is None:
        return _render(request, "dashboard.html", "dashboard", 503, viewer=v, board=None)
    try:
        board = service.dashboard(v.user, v.token)
    except SupabaseError as e:
        return _render(request, "dashboard.html", "dashboard", 503, viewer=v, board=None, error=str(e))
    return _render(request, "dashboard.html", "dashboard", viewer=v, board=board)


def _dashboard_action(request: Request, v, action, target: str, done: str) -> Response:
    try:
        action(v.user, target)
    except (DonationError, SupabaseError) as e:
        return _back(request, "/dashboard", str(e), "error")
    return _back(request, "/dashboard", done)


@router.post("/dashboard/requests/{request_id}/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, request_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().approve_request, request_id,
                             "Request approved. You can now see each other's contact note.")


@router.post("/dashboard/requests/{request_id}/decline", dependencies=[Depends(verify_csrf)])
def decline(request: Request, request_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().decline_request, request_id, "Request declined.")


@router.post("/dashboard/requests/{request_id}/withdraw", dependencies=[Depends(verify_csrf)])
def withdraw(request: Request, request_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().withdraw_request, request_id, "Your request was withdrawn.")


@router.post("/dashboard/listings/{listing_id}/complete", dependencies=[Depends(verify_csrf)])
def complete(request: Request, listing_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().complete_listing, listing_id,
                             "Marked as handed over. Thank you for giving it a second life!")


@router.post("/dashboard/listings/{listing_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, listing_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().cancel_reservation, listing_id,
                             "Reservation cancelled. The item is available again.")


@router.post("/dashboard/listings/{listing_id}/delete", dependencies=[Depends(verify_csrf)])
def delete(request: Request, listing_id: str, v=Depends(require_user)) -> Response:
    return _dashboard_action(request, v, donation_service().delete_listing, listing_id, "Listing removed.")


# ---------- admin ----------

@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, v=Depends(require_user)) -> HTMLResponse:
    if not v.user.is_admin:
        return _render(request, "admin.html", "admin", 403, viewer=v, queue=None)
    try:
        queue = donation_service().pending_queue(v.user)
    except SupabaseError as e:
        return _render(request, "admin.html", "admin", 503, viewer=v, queue=[], error=str(e))
    return _render(request, "admin.html", "admin", viewer=v, queue=queue)


@router.post("/admin/listings/{listing_id}/approve", dependencies=[Depends(verify_csrf)])
def admin_approve(request: Request, listing_id: str, v=Depends(require_user)) -> Response:
    try:
        donation_service().admin_approve(v.user, listing_id)
    except (DonationError, SupabaseError) as e:
        return _back(request, "/admin", str(e), "error")
    return _back(request, "/admin", "Listing approved. It's now public.")


@router.post("/admin/listings/{listing_id}/reject", dependencies=[Depends(verify_csrf)])
def admin_reject(request: Request, listing_id: str, v=Depends(require_user), reason: str = Form("")) -> Response:
    try:
        donation_service().admin_reject(v.user, listing_id, reason)
    except (DonationError, SupabaseError) as e:
        return _back(request, "/admin", str(e), "error")
    return _back(request, "/admin", "Listing rejected. The donor will see your reason.")
