"""Session cookies and CSRF protection for the server-rendered forms.

* Session: the Supabase access and refresh tokens, in an HttpOnly, SameSite=Lax cookie
  (Secure on HTTPS). Scripts on the page can't read it.
* CSRF: a random token in its own cookie, repeated as a hidden field in every form that
  changes something. A forged post from another site can't know it.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets

from fastapi import Form, HTTPException, Request
from markupsafe import Markup, escape
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from reloop.database.supabase import Session

SESSION_COOKIE = "rl_session"
CSRF_COOKIE = "rl_csrf"
FLASH_COOKIE = "rl_flash"
SESSION_MAX_AGE = 30 * 24 * 3600  # matches Supabase's default refresh-token lifetime


def encode_session(session: Session) -> str:
    return base64.urlsafe_b64encode(session.model_dump_json().encode()).decode()


def decode_session(raw: str | None) -> Session | None:
    if not raw:
        return None
    try:
        return Session.model_validate(json.loads(base64.urlsafe_b64decode(raw.encode())))
    except (ValueError, ValidationError):
        return None


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def set_session(request: Request, session: Session) -> None:
    """Ask the middleware to write this session cookie on the response."""
    request.state.session_update = session


def clear_session(request: Request) -> None:
    request.state.session_update = False


def flash(request: Request, message: str, kind: str = "ok") -> None:
    """Show a one-time message on the next page (after a redirect)."""
    request.state.flash_out = {"m": message[:300], "k": "error" if kind == "error" else "ok"}


def take_flash(request: Request) -> dict | None:
    """The message set by the previous request, shown once."""
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    request.state.flash_consumed = True
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode()))
        return {"m": str(data["m"])[:300], "k": "error" if data.get("k") == "error" else "ok"}
    except (ValueError, KeyError, TypeError):
        return None


def csrf_token(request: Request) -> str:
    return request.state.csrf


def csrf_field(request: Request) -> Markup:
    return Markup(f'<input type="hidden" name="csrf_token" value="{escape(csrf_token(request))}">')


def verify_csrf(request: Request, csrf_token: str = Form("")) -> None:
    """FastAPI dependency for every state-changing form post."""
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not csrf_token or not hmac.compare_digest(cookie, csrf_token):
        raise HTTPException(status_code=403, detail="Your form expired. Please go back, refresh the page and try again.")


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        existing = request.cookies.get(CSRF_COOKIE)
        request.state.csrf = existing or secrets.token_urlsafe(32)
        request.state.session_update = None
        request.state.flash_out = None
        request.state.flash_consumed = False
        response = await call_next(request)
        secure = _secure(request)
        if not existing:
            response.set_cookie(CSRF_COOKIE, request.state.csrf, httponly=True, samesite="lax", secure=secure, path="/")
        update = request.state.session_update
        if update is False:
            response.delete_cookie(SESSION_COOKIE, path="/")
        elif update is not None:
            response.set_cookie(SESSION_COOKIE, encode_session(update), max_age=SESSION_MAX_AGE,
                                httponly=True, samesite="lax", secure=secure, path="/")
        if request.state.flash_out:
            raw = base64.urlsafe_b64encode(json.dumps(request.state.flash_out).encode()).decode()
            response.set_cookie(FLASH_COOKIE, raw, max_age=120, httponly=True, samesite="lax", secure=secure, path="/")
        elif request.state.flash_consumed:
            response.delete_cookie(FLASH_COOKIE, path="/")
        if request.cookies.get(SESSION_COOKIE) or update:
            response.headers["Cache-Control"] = "private, no-store"  # never cache signed-in pages
        for name, value in security_headers(secure).items():
            response.headers.setdefault(name, value)
        return response


def _photo_origin() -> str:
    from reloop.config import get_settings

    url = get_settings().supabase_url.strip().rstrip("/")
    return url if url.startswith("https://") else ""


# The ElevenLabs voice widget, used on /talk only. Pinned to one reviewed version and checked
# with Subresource Integrity, so an unreviewed update can't run on the site.
VOICE_WIDGET_VERSION = "0.24.1"
VOICE_WIDGET_SRC = f"https://unpkg.com/@elevenlabs/convai-widget-embed@{VOICE_WIDGET_VERSION}/dist/index.js"
VOICE_WIDGET_SRI = "sha384-B4uAhBswsi7DItpkOMjD0LFyy8AxRDYQTIzwJV1rKWZ1a1zI1Fd/4VE5vy6Ua43S"
_VOICE_WIDGET_POLICY = {
    # the widget, its audio resampler worklet, and worklets it builds in memory
    "script-src": f"'self' {VOICE_WIDGET_SRC} https://cdn.jsdelivr.net/npm/@alexanderolsen/libsamplerate-js@2.1.2/ blob:",
    "worker-src": "blob:",
    # ElevenLabs API and its LiveKit voice connection. Nothing else (fingerprinting telemetry and Google Fonts stay blocked).
    "connect-src": ("https://api.elevenlabs.io wss://api.elevenlabs.io https://api.us.elevenlabs.io wss://api.us.elevenlabs.io "
                    "https://livekit.rtc.elevenlabs.io wss://livekit.rtc.elevenlabs.io"),
    "style-src": "'self' 'unsafe-inline'",  # the widget styles its own shadow DOM
    "media-src": "'self' blob: mediastream:",
    "img-src": "'self' data: https://storage.googleapis.com/eleven-public-cdn/",
}


def security_headers(secure: bool, voice_widget: bool = False) -> dict[str, str]:
    """The only script is our own /js/scan.js (no inline scripts, no inline styles), so the
    policy stays strict. Listing photos come from Supabase Storage through short-lived signed links.
    `voice_widget` widens it just enough for the ElevenLabs widget, on the /talk page only."""
    policy = {
        "default-src": "'self'",
        "script-src": "'self'",
        "connect-src": "'none'",
        "style-src": "'self'",
        "font-src": "'self'",
        "img-src": f"'self' data: {_photo_origin()}".strip(),
        "form-action": "'self'",
        "frame-ancestors": "'none'",
        "base-uri": "'none'",
        "object-src": "'none'",
    }
    if voice_widget:
        policy.update(_VOICE_WIDGET_POLICY)
    csp = "; ".join([f"{name} {value}" for name, value in policy.items()]
                    + (["upgrade-insecure-requests"] if secure else []))
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": f"camera=(), microphone={'(self)' if voice_widget else '()'}, geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if secure:
        headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return headers
