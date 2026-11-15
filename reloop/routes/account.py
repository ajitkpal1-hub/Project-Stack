"""Accounts: sign up, log in, log out, and the profile (name, locality, PIN, private contact note)."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from reloop.database.supabase import AuthError, SupabaseError
from reloop.models.donations import ProfileForm
from reloop.routes.deps import accounts_ready, auth_backend, donation_service, require_user, safe_next, viewer
from reloop.security import clear_session, flash, set_session, verify_csrf
from reloop.templating import templates

router = APIRouter()
log = logging.getLogger("reloop.account")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


def _auth_page(request: Request, mode: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth.html", {"active": "dashboard", "mode": mode,
                                      "ready": accounts_ready(), "min_password": MIN_PASSWORD, **ctx},
                                      status_code=status_code)


def _validate(email: str, password: str) -> str | None:
    if not EMAIL_RE.match(email) or len(email) > 254:
        return "Please enter a valid email address."
    if len(password) < MIN_PASSWORD:
        return f"Please use a password of at least {MIN_PASSWORD} characters."
    if len(password) > 72:
        return "Please use a password of 72 characters or fewer."
    return None


@router.get("/account/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "") -> Response:
    if viewer(request).signed_in:
        return RedirectResponse(safe_next(next), status_code=303)
    return _auth_page(request, "login", next=safe_next(next))


@router.get("/account/signup", response_class=HTMLResponse)
def signup_page(request: Request, next: str = "") -> Response:
    if viewer(request).signed_in:
        return RedirectResponse(safe_next(next), status_code=303)
    return _auth_page(request, "signup", next=safe_next(next))


@router.post("/account/login", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def login_submit(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("")) -> Response:
    backend = auth_backend()
    email = email.strip().lower()
    if backend is None:
        return _auth_page(request, "login", 503, next=safe_next(next), email=email)
    if not email or not password:
        return _auth_page(request, "login", 422, next=safe_next(next), email=email, error="Please enter your email and password.")
    try:
        session = backend.sign_in(email, password)
    except SupabaseError as e:
        return _auth_page(request, "login", 400 if isinstance(e, AuthError) else 503, next=safe_next(next), email=email, error=str(e))
    set_session(request, session)
    flash(request, "You're logged in.")
    return RedirectResponse(safe_next(next), status_code=303)


@router.post("/account/signup", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def signup_submit(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form("")) -> Response:
    backend = auth_backend()
    email = email.strip().lower()
    if backend is None:
        return _auth_page(request, "signup", 503, next=safe_next(next), email=email)
    problem = _validate(email, password)
    if problem:
        return _auth_page(request, "signup", 422, next=safe_next(next), email=email, error=problem)
    try:
        session = backend.sign_up(email, password)
    except SupabaseError as e:
        return _auth_page(request, "signup", 400 if isinstance(e, AuthError) else 503, next=safe_next(next), email=email, error=str(e))
    if session is None:
        return _auth_page(request, "login", 200, next=safe_next(next), email=email,
                          notice="Account created. Please confirm your email using the link we sent, then log in.")
    set_session(request, session)
    log.info("account created")
    flash(request, "Welcome to RELOOP AI! Add your locality so donations can be matched nearby.")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request) -> Response:
    v = viewer(request)
    backend = auth_backend()
    if v.token and backend:
        backend.sign_out(v.token)
    clear_session(request)
    flash(request, "You're logged out.")
    return RedirectResponse("/", status_code=303)


def _profile_page(request: Request, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, "account.html", {"active": "dashboard", **ctx}, status_code=status_code)


@router.get("/account", response_class=HTMLResponse)
def profile_page(request: Request, v=Depends(require_user)) -> HTMLResponse:
    service = donation_service()
    profile = None
    if service:
        try:
            profile = service.repo.get_profile(v.user.id)
        except SupabaseError as e:
            return _profile_page(request, 503, form=ProfileForm(), error=str(e))
    form = ProfileForm(**profile.model_dump(exclude={"id"})) if profile else ProfileForm()
    return _profile_page(request, form=form)


@router.post("/account", response_class=HTMLResponse, dependencies=[Depends(verify_csrf)])
def profile_save(request: Request, v=Depends(require_user), display_name: str = Form(""), locality: str = Form(""),
                 pin_code: str = Form(""), contact_note: str = Form("")) -> Response:
    raw = {"display_name": display_name, "locality": locality, "pin_code": pin_code, "contact_note": contact_note}
    try:
        form = ProfileForm(**raw)
    except ValidationError as e:
        return _profile_page(request, 422, form=ProfileForm.model_construct(**raw), error=_first_error(e))
    service = donation_service()
    try:
        service.repo.save_profile(v.user.id, form, v.token)
    except SupabaseError as e:
        return _profile_page(request, 503, form=form, error=str(e))
    flash(request, "Profile saved.")
    return RedirectResponse("/dashboard", status_code=303)


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    msg = str(err.get("msg", "Please check the form."))
    return msg.removeprefix("Value error, ")
