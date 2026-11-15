"""Saved scans and answers, AI-answer reports, and the admin overview, knowledge and reports pages."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from reloop.database.supabase import SupabaseError
from reloop.models.categories import LANES_BY_CATEGORY
from reloop.models.dashboards import FLAG_REASON_LABELS
from reloop.routes.deps import dashboard_service, rate_limiter, require_user, viewer
from reloop.security import flash, verify_csrf
from reloop.services.dashboards import DashboardError
from reloop.templating import templates

router = APIRouter()
BACK = {"scan": "/scan", "answer": "/assistant"}


def _back(request: Request, to: str, message: str, kind: str = "ok") -> RedirectResponse:
    flash(request, message, kind)
    return RedirectResponse(to, status_code=303)


def _render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, template, {"active": "admin", "reason_labels": FLAG_REASON_LABELS,
                                                          "lanes_by_category": LANES_BY_CATEGORY, **ctx}, status_code=status_code)


# ---------- members ----------

@router.post("/saved", dependencies=[Depends(verify_csrf)])
def save(request: Request, v=Depends(require_user), kind: str = Form(""), payload: str = Form("")) -> Response:
    service = dashboard_service()
    try:
        service.save(v.user, v.token, kind, payload)
    except (DashboardError, SupabaseError) as e:
        return _back(request, BACK.get(kind, "/dashboard"), str(e), "error")
    return _back(request, "/dashboard#saved", "Saved to your dashboard.")


@router.post("/saved/{item_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_saved(request: Request, item_id: str, v=Depends(require_user)) -> Response:
    try:
        dashboard_service().delete(v.user, v.token, item_id)
    except SupabaseError as e:
        return _back(request, "/dashboard#saved", str(e), "error")
    return _back(request, "/dashboard#saved", "Deleted.")


@router.post("/report", dependencies=[Depends(verify_csrf)])
def report(request: Request, kind: str = Form(""), reason: str = Form(""), note: str = Form(""), payload: str = Form("")) -> Response:
    service = dashboard_service()
    to = BACK.get(kind, "/")
    if service is None:
        return _back(request, to, "Reporting isn't switched on yet. Thank you for trying.", "error")
    limited = rate_limiter().check(request, "report")
    if limited:
        return _back(request, to, limited, "error")
    try:
        service.report(viewer(request).user, kind, reason, note, payload)
    except (DashboardError, SupabaseError) as e:
        return _back(request, to, str(e), "error")
    return _back(request, to, "Thank you. Our team will review that answer.")


# ---------- admins ----------

def _admin_or_403(request: Request, v, template: str, **empty) -> HTMLResponse | None:
    if not v.user.is_admin:
        return _render(request, template, 403, viewer=v, forbidden=True, **empty)
    return None


@router.get("/admin", response_class=HTMLResponse)
def admin_overview(request: Request, v=Depends(require_user)) -> HTMLResponse:
    denied = _admin_or_403(request, v, "admin_overview.html", stats=None)
    if denied:
        return denied
    try:
        stats = dashboard_service().overview(v.user)
    except (DashboardError, SupabaseError) as e:
        return _render(request, "admin_overview.html", 503, viewer=v, stats=None, error=str(e))
    return _render(request, "admin_overview.html", viewer=v, stats=stats)


@router.get("/admin/flags", response_class=HTMLResponse)
def admin_flags(request: Request, v=Depends(require_user)) -> HTMLResponse:
    denied = _admin_or_403(request, v, "admin_flags.html", flags=[])
    if denied:
        return denied
    try:
        flags = dashboard_service().open_flags(v.user)
    except (DashboardError, SupabaseError) as e:
        return _render(request, "admin_flags.html", 503, viewer=v, flags=[], error=str(e))
    return _render(request, "admin_flags.html", viewer=v, flags=flags)


@router.post("/admin/flags/{flag_id}/resolve", dependencies=[Depends(verify_csrf)])
def admin_resolve(request: Request, flag_id: str, v=Depends(require_user), admin_note: str = Form("")) -> Response:
    try:
        dashboard_service().resolve(v.user, flag_id, admin_note)
    except (DashboardError, SupabaseError) as e:
        return _back(request, "/admin/flags", str(e), "error")
    return _back(request, "/admin/flags", "Report closed.")


@router.get("/admin/knowledge", response_class=HTMLResponse)
def admin_knowledge(request: Request, v=Depends(require_user)) -> HTMLResponse:
    denied = _admin_or_403(request, v, "admin_knowledge.html", docs=[])
    if denied:
        return denied
    try:
        docs = dashboard_service().documents(v.user)
    except (DashboardError, SupabaseError) as e:
        return _render(request, "admin_knowledge.html", 503, viewer=v, docs=[], error=str(e))
    return _render(request, "admin_knowledge.html", viewer=v, docs=docs)


@router.post("/admin/knowledge/{doc_id}/{action}", dependencies=[Depends(verify_csrf)])
def admin_set_document(request: Request, doc_id: str, action: str, v=Depends(require_user)) -> Response:
    if action not in {"archive", "restore"}:
        return _back(request, "/admin/knowledge", "Unknown action.", "error")
    try:
        dashboard_service().set_document(v.user, doc_id, active=action == "restore")
    except (DashboardError, SupabaseError) as e:
        return _back(request, "/admin/knowledge", str(e), "error")
    return _back(request, "/admin/knowledge", "Document restored. The assistant uses it again." if action == "restore"
                 else "Document archived. The assistant no longer quotes it.")
