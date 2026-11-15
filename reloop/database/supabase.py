"""Thin Supabase REST client: Auth (GoTrue), database (PostgREST) and Storage.

Three ways to call the database:
  * anon      - public key, no user: row-level security shows only public rows.
  * user      - public key + the user's own token: RLS applies as that user.
  * service   - service-role key: bypasses RLS. Server only, used after our own checks.
Keys and tokens are never logged.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel

log = logging.getLogger("reloop.supabase")


class SupabaseError(RuntimeError):
    """A Supabase call failed. The message is safe to show users."""


class AuthError(SupabaseError):
    """Sign-in or sign-up was refused. The message is safe to show users."""


class Session(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int  # unix seconds
    user_id: str
    email: str

    def expired(self, leeway_s: int = 60) -> bool:
        return time.time() + leeway_s >= self.expires_at


def _session_from(data: dict[str, Any]) -> Session:
    user = data.get("user") or {}
    expires_at = data.get("expires_at") or int(time.time()) + int(data.get("expires_in") or 3600)
    return Session(access_token=data["access_token"], refresh_token=data["refresh_token"], expires_at=int(expires_at),
                   user_id=user.get("id", ""), email=user.get("email", ""))


_AUTH_MESSAGES = {
    "invalid_credentials": "That email and password don't match. Please try again.",
    "user_already_exists": "An account with this email already exists. Please log in instead.",
    "email_exists": "An account with this email already exists. Please log in instead.",
    "weak_password": "Please choose a stronger password: at least 8 characters.",
    "email_not_confirmed": "Please confirm your email address first, using the link we sent you.",
    "over_request_rate_limit": "Too many attempts. Please wait a minute and try again.",
    "over_email_send_rate_limit": "Too many sign-ups right now. Please try again in a few minutes.",
    "signup_disabled": "New sign-ups are paused right now.",
    "email_address_invalid": "Please enter a valid email address.",
    "validation_failed": "Please enter a valid email address and password.",
}


class SupabaseClient:
    def __init__(self, url: str, anon_key: str, service_key: str, timeout_s: float = 15.0):
        self.url = url.rstrip("/")
        self._anon = anon_key
        self._service = service_key
        self._timeout = timeout_s

    # ---------- auth ----------
    def _auth(self, method: str, path: str, *, json: dict | None = None, token: str | None = None) -> httpx.Response:
        headers = {"apikey": self._anon, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return httpx.request(method, f"{self.url}/auth/v1{path}", json=json, headers=headers, timeout=self._timeout)
        except httpx.HTTPError:
            log.error("supabase auth connection error")
            raise SupabaseError("We couldn't reach the sign-in service. Please try again shortly.") from None

    @staticmethod
    def _auth_failure(r: httpx.Response) -> AuthError:
        try:
            body = r.json()
        except ValueError:
            body = {}
        code = str(body.get("error_code") or body.get("code") or body.get("error") or "")
        log.warning("supabase auth refused status=%s code=%s", r.status_code, code)
        if code in _AUTH_MESSAGES:
            return AuthError(_AUTH_MESSAGES[code])
        if r.status_code == 429:
            return AuthError(_AUTH_MESSAGES["over_request_rate_limit"])
        if r.status_code in (400, 401, 422):
            return AuthError("We couldn't sign you in with those details. Please check them and try again.")
        return AuthError("The sign-in service had a problem. Please try again shortly.")

    def sign_up(self, email: str, password: str) -> Session | None:
        """Returns a session, or None when Supabase wants the email confirmed first."""
        r = self._auth("POST", "/signup", json={"email": email, "password": password})
        if r.status_code not in (200, 201):
            raise self._auth_failure(r)
        data = r.json()
        if data.get("access_token"):
            return _session_from(data)
        # Duplicate emails come back as a user with no identities (anti-enumeration).
        if data.get("identities") == [] or (data.get("user") or {}).get("identities") == []:
            raise AuthError(_AUTH_MESSAGES["user_already_exists"])
        return None

    def sign_in(self, email: str, password: str) -> Session:
        r = self._auth("POST", "/token?grant_type=password", json={"email": email, "password": password})
        if r.status_code != 200:
            raise self._auth_failure(r)
        return _session_from(r.json())

    def refresh(self, refresh_token: str) -> Session:
        r = self._auth("POST", "/token?grant_type=refresh_token", json={"refresh_token": refresh_token})
        if r.status_code != 200:
            raise self._auth_failure(r)
        return _session_from(r.json())

    def get_user(self, access_token: str) -> dict[str, Any] | None:
        r = self._auth("GET", "/user", token=access_token)
        if r.status_code != 200:
            return None
        return r.json()

    def sign_out(self, access_token: str) -> None:
        try:
            self._auth("POST", "/logout", token=access_token)
        except SupabaseError:
            pass  # the cookie is cleared anyway

    # ---------- database ----------
    def rest(self, method: str, path: str, *, token: str | None = None, service: bool = False,
             json: Any = None, params: dict[str, str] | None = None, prefer: str | None = None) -> Any:
        key = self._service if service else self._anon
        headers = {"apikey": key, "Content-Type": "application/json"}
        if service:
            headers["Authorization"] = f"Bearer {self._service}"
        elif token:
            headers["Authorization"] = f"Bearer {token}"
        if prefer:
            headers["Prefer"] = prefer
        try:
            r = httpx.request(method, f"{self.url}/rest/v1{path}", json=json, params=params, headers=headers, timeout=self._timeout)
        except httpx.HTTPError:
            log.error("supabase rest connection error path=%s", path.split("?")[0])
            raise SupabaseError("We couldn't reach the database. Please try again shortly.") from None
        if r.status_code >= 400:
            log.error("supabase rest error status=%s path=%s", r.status_code, path.split("?")[0])
            raise SupabaseError("Something went wrong saving or loading that. Please try again.")
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    # ---------- storage (service role only; the bucket is private) ----------
    def _storage(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {"apikey": self._service, "Authorization": f"Bearer {self._service}", **kw.pop("headers", {})}
        try:
            r = httpx.request(method, f"{self.url}/storage/v1{path}", headers=headers, timeout=self._timeout, **kw)
        except httpx.HTTPError:
            log.error("supabase storage connection error")
            raise SupabaseError("We couldn't reach photo storage. Please try again shortly.") from None
        if r.status_code >= 400:
            log.error("supabase storage error status=%s", r.status_code)
            raise SupabaseError("We couldn't save or load the photo. Please try again.")
        return r

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        self._storage("POST", f"/object/{bucket}/{path}", content=data,
                      headers={"Content-Type": content_type, "x-upsert": "false"})

    def signed_url(self, bucket: str, path: str, expires_in: int = 3600) -> str:
        r = self._storage("POST", f"/object/sign/{bucket}/{path}", json={"expiresIn": expires_in})
        signed = r.json().get("signedURL") or r.json().get("signedUrl") or ""
        return f"{self.url}/storage/v1{signed}" if signed.startswith("/") else signed

    def remove(self, bucket: str, paths: list[str]) -> None:
        if paths:
            self._storage("DELETE", f"/object/{bucket}", json={"prefixes": paths})
