"""Find recycling centres: search, member suggestions, and the admin directory tools."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from reloop.database.supabase import SupabaseError
from reloop.models.categories import LANES, LANES_BY_CATEGORY, WasteCategory
from reloop.models.donations import CATEGORY_LABELS
from reloop.models.partners import KIND_LABELS, PartnerForm
from reloop.routes.account import _first_error
from reloop.routes.deps import login_url, partner_repo, partner_service, require_user, viewer
from reloop.security import flash, verify_csrf
from reloop.services.partners import PartnerError
from reloop.templating import templates

router = APIRouter()

COMMON = {"lanes": LANES, "lanes_by_category": LANES_BY_CATEGORY, "kind_labels": KIND_LABELS, "category_labels": CATEGORY_LABELS}


def _render(request: Request, template: str, active: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, template, {**COMMON, "active": active, "directory_ready": partner_repo() is not None, **ctx},
                                      status_code=status_code)


def _material(value: str) -> WasteCategory | None:
    try:
        return WasteCategory(value) if value else None
    except ValueError:
        return None


def _back(request: Request, to: str, message: str, kind: str = "ok") -> RedirectResponse:
    flash(request, message, kind)
    return RedirectResponse(to, status_code=303)


def _form_from(raw: dict, materials: list[str], donation_categories: list[str]) -> PartnerForm:
    return PartnerForm(**raw, materials=[m for m in materials if m], donation_categories=[c for c in donation_categories if c])


# ---------- search ----------

@router.get("/centres", response_class=HTMLResponse)
def centres(request: Request, place: str = "", material: str = "") -> HTMLResponse:
    chosen = _material(material)
    result = partner_service().search(place, chosen) if (place.strip() or chosen) else None
    return _render(request, "centres.html", "centres", viewer=viewer(request), result=result,
                   place=" ".join(place.split())[:80], material=chosen.value if chosen else "")


# ---------- member suggestions ----------

@router.get("/centres/suggest", response_class=HTMLResponse)
def suggest_page(request: Request, name: str = "", locality: str = "", pin_code: str = "", latitude: str = "",
                 longitude: str = "", material: str = "") -> HTMLResponse:
    v = viewer(request)
    prefill = {"name": name[:120], "locality": locality[:80], "pin_code": pin_code[:6], "latitude": latitude[:20],
               "longitude": longitude[:20], "materials": [material] if _material(material) else []}
    return _render(request, "partner_form.html", "centres", viewer=v, form=prefill, mode="suggest",
                   login_link=login_url(str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")))


@router.post("/centres/suggest", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def suggest_submit(request: Request, v=Depends(require_user), name: str = Form(""), kind: str = Form(""),
                   materials: list[str] = Form([]), donation_categories: list[str] = Form([]), address: str = Form(""),
                   locality: str = Form(""), city: str = Form(""), pin_code: str = Form(""), phone: str = Form(""),
                   website: str = Form(""), source_url: str = Form(""), latitude: str = Form(""), longitude: str = Form("")) -> Response:
    raw = dict(name=name, kind=kind, address=address, locality=locality, city=city, pin_code=pin_code, phone=phone,
               website=website, source_url=source_url, latitude=latitude, longitude=longitude)
    shown = {**raw, "materials": materials, "donation_categories": donation_categories}
    try:
        form = _form_from(raw, materials, donation_categories)
        partner_service().suggest(v.user, v.token, form)
    except ValidationError as e:
        return _render(request, "partner_form.html", "centres", 422, viewer=v, form=shown, mode="suggest", error=_first_error(e))
    except (PartnerError, SupabaseError) as e:
        return _render(request, "partner_form.html", "centres", 503, viewer=v, form=shown, mode="suggest", error=str(e))
    return _back(request, "/centres", "Thanks! An admin will check this place before it appears in the directory.")


# ---------- admin ----------

@router.get("/admin/partners", response_class=HTMLResponse)
def admin_partners(request: Request, v=Depends(require_user), name: str = "", locality: str = "", pin_code: str = "",
                   latitude: str = "", longitude: str = "") -> HTMLResponse:
    if not v.user.is_admin:
        return _render(request, "admin_partners.html", "admin", 403, viewer=v, pending=None, verified=[], form={})
    service = partner_service()
    try:
        pending = service.pending(v.user)
        verified = service.repo.verified()
    except (PartnerError, SupabaseError) as e:
        return _render(request, "admin_partners.html", "admin", 503, viewer=v, pending=[], verified=[], form={}, error=str(e))
    prefill = {"name": name[:120], "locality": locality[:80], "pin_code": pin_code[:6], "latitude": latitude[:20], "longitude": longitude[:20]}
    return _render(request, "admin_partners.html", "admin", viewer=v, pending=pending, verified=verified, form=prefill)


@router.post("/admin/partners", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def admin_add(request: Request, v=Depends(require_user), name: str = Form(""), kind: str = Form(""),
              materials: list[str] = Form([]), donation_categories: list[str] = Form([]), address: str = Form(""),
              locality: str = Form(""), city: str = Form(""), pin_code: str = Form(""), phone: str = Form(""),
              website: str = Form(""), source_url: str = Form(""), latitude: str = Form(""), longitude: str = Form("")) -> Response:
    raw = dict(name=name, kind=kind, address=address, locality=locality, city=city, pin_code=pin_code, phone=phone,
               website=website, source_url=source_url, latitude=latitude, longitude=longitude)
    service = partner_service()

    def again(code: int, error: str) -> HTMLResponse:
        try:
            pending, verified = (service.pending(v.user), service.repo.verified()) if v.user.is_admin else (None, [])
        except (PartnerError, SupabaseError):
            pending, verified = [], []
        return _render(request, "admin_partners.html", "admin", code, viewer=v, pending=pending, verified=verified,
                       form={**raw, "materials": materials, "donation_categories": donation_categories}, error=error)
    try:
        service.admin_add(v.user, _form_from(raw, materials, donation_categories))
    except ValidationError as e:
        return again(422, _first_error(e))
    except (PartnerError, SupabaseError) as e:
        return again(422 if isinstance(e, PartnerError) else 503, str(e))
    return _back(request, "/admin/partners", "Added to the verified directory.")


def _admin_action(request: Request, v, action, entry_id: str, done: str) -> Response:
    try:
        action(v.user, entry_id)
    except (PartnerError, SupabaseError) as e:
        return _back(request, "/admin/partners", str(e), "error")
    return _back(request, "/admin/partners", done)


@router.post("/admin/partners/{entry_id}/verify", dependencies=[Depends(verify_csrf)])
def admin_verify(request: Request, entry_id: str, v=Depends(require_user)) -> Response:
    return _admin_action(request, v, partner_service().verify, entry_id, "Verified. It now shows in search results.")


@router.post("/admin/partners/{entry_id}/reject", dependencies=[Depends(verify_csrf)])
def admin_reject(request: Request, entry_id: str, v=Depends(require_user)) -> Response:
    return _admin_action(request, v, partner_service().reject, entry_id, "Suggestion rejected.")


@router.post("/admin/partners/{entry_id}/remove", dependencies=[Depends(verify_csrf)])
def admin_remove(request: Request, entry_id: str, v=Depends(require_user)) -> Response:
    return _admin_action(request, v, partner_service().remove, entry_id, "Removed from the directory.")
