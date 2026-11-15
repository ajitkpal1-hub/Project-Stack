"""Shared route helpers: who is signed in, and the donation service.

`viewer(request)` confirms the session with Supabase Auth on each request (refreshing
an expired token when it can), so a revoked session stops working straight away.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from fastapi import Request

from reloop.config import get_settings
from reloop.database.donations import DonationRepo, SupabaseDonationRepo
from reloop.database.supabase import AuthError, Session, SupabaseClient, SupabaseError
from reloop.models.donations import User
from reloop.security import SESSION_COOKIE, clear_session, decode_session, set_session
from reloop.services.donations import DonationService

log = logging.getLogger("reloop.auth")


class AuthBackend(Protocol):
    def sign_up(self, email: str, password: str) -> Session | None: ...
    def sign_in(self, email: str, password: str) -> Session: ...
    def refresh(self, refresh_token: str) -> Session: ...
    def get_user(self, access_token: str) -> dict | None: ...
    def sign_out(self, access_token: str) -> None: ...


# Test hooks: swap in fakes without touching settings.
_auth_override: AuthBackend | None = None
_repo_override: DonationRepo | None = None

# Per-instance cache of confirmed tokens, so a page with several lookups checks once.
_VERIFIED: dict[str, tuple[float, dict]] = {}
_VERIFY_TTL_S = 60.0


def _client() -> SupabaseClient | None:
    s = get_settings()
    if not s.accounts_ready:
        return None
    return SupabaseClient(s.supabase_url.strip(), s.supabase_anon_key.strip(), s.supabase_service_role_key.strip())


def auth_backend() -> AuthBackend | None:
    return _auth_override if _auth_override is not None else _client()


def donation_service() -> DonationService | None:
    if _repo_override is not None:
        return DonationService(_repo_override)
    client = _client()
    return DonationService(SupabaseDonationRepo(client)) if client else None


def accounts_ready() -> bool:
    return auth_backend() is not None and donation_service() is not None


@dataclass
class Viewer:
    user: User | None = None
    token: str | None = None

    @property
    def signed_in(self) -> bool:
        return self.user is not None


def _to_user(data: dict) -> User:
    email = (data.get("email") or "").lower()
    return User(id=data["id"], email=email, is_admin=email in get_settings().admin_email_set)


def _verify(backend: AuthBackend, token: str) -> dict | None:
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _VERIFIED.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    data = backend.get_user(token)
    if data and data.get("id"):
        if len(_VERIFIED) > 1000:
            _VERIFIED.clear()
        _VERIFIED[key] = (time.monotonic() + _VERIFY_TTL_S, data)
        return data
    return None


def viewer(request: Request) -> Viewer:
    cached = getattr(request.state, "viewer", None)
    if cached is not None:
        return cached
    result = Viewer()
    session = decode_session(request.cookies.get(SESSION_COOKIE))
    backend = auth_backend() if session else None
    if session and backend:
        try:
            if session.expired():
                session = backend.refresh(session.refresh_token)
                set_session(request, session)
            data = _verify(backend, session.access_token)
            if data is None:  # revoked or rotated: one refresh attempt
                session = backend.refresh(session.refresh_token)
                set_session(request, session)
                data = _verify(backend, session.access_token)
            if data:
                result = Viewer(user=_to_user(data), token=session.access_token)
            else:
                clear_session(request)
        except AuthError:
            clear_session(request)
        except SupabaseError:
            log.warning("auth service unreachable; treating visitor as signed out for this request")
    elif session:
        clear_session(request)
    request.state.viewer = result
    return result


class LoginRequired(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


def login_url(next_path: str) -> str:
    return f"/account/login?next={quote(next_path, safe='/')}"


def require_user(request: Request) -> Viewer:
    v = viewer(request)
    if not v.signed_in:
        raise LoginRequired(request.url.path)
    return v


def safe_next(path: str | None) -> str:
    """Only allow redirects back to our own pages."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/dashboard"
    return path
