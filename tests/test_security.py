"""Phase 9: security hardening. Headers, upload bombs, usage limits, error pages, auth edge cases."""

from __future__ import annotations

import io
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reloop.config import get_settings
from reloop.database.memory import InMemoryDonationRepo
from reloop.database.supabase import SupabaseClient, SupabaseError
from reloop.routes import deps
from reloop.routes import scan as scan_route
from reloop.services.classifier import MockClassifier
from reloop.services.ratelimit import POLICIES, SITE_CAP_MESSAGE, MemoryCounter, RateLimiter, SupabaseCounter, client_ip, visitor_key
from reloop.utils.images import ImageValidationError, prepare_image
from reloop.web import create_app
from tests.test_donations import FakeAuth, signup
from tests.test_scan import make_image, post_photo


@pytest.fixture
def client():
    yield TestClient(create_app())
    scan_route._classifier_override = None


# ---------- headers ----------

@pytest.mark.parametrize("path", ["/", "/scan", "/donations", "/account/login", "/no-such-page"])
def test_security_headers_on_pages(client, path):
    h = client.get(path).headers
    csp = h["content-security-policy"]
    assert "script-src 'self'" in csp and "connect-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "'unsafe-inline'" not in csp
    assert "base-uri 'none'" in csp and "form-action 'self'" in csp
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in h  # plain http in tests: only sent over HTTPS


def test_hsts_and_upgrade_over_https():
    c = TestClient(create_app(), base_url="https://testserver")
    h = c.get("/").headers
    assert h["strict-transport-security"].startswith("max-age=")
    assert "upgrade-insecure-requests" in h["content-security-policy"]


def test_photo_host_allowed_only_when_https(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    get_settings.cache_clear()
    assert "img-src 'self' data: https://abc.supabase.co" in TestClient(create_app()).get("/").headers["content-security-policy"]


def test_templates_have_no_inline_scripts_or_styles(client):
    for path in ["/", "/scan", "/assistant", "/donate", "/donations", "/centres", "/account/login", "/account/signup"]:
        html = client.get(path).text.lower()
        inline_scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html)
        assert not inline_scripts and " style=" not in html and "javascript:" not in html and " onclick=" not in html, path
        assert re.findall(r'<script src="([^"]+)"', html) == ["/js/scan.js?v=0.2.1"], path  # our own file only


# ---------- uploads ----------

@pytest.mark.parametrize("side", [12000, 20000])
def test_decompression_bombs_are_refused(side):
    buf = io.BytesIO()
    Image.new("1", (side, side)).save(buf, "PNG")
    assert len(buf.getvalue()) < 200_000  # tiny file, enormous image
    with pytest.raises(ImageValidationError):
        prepare_image(buf.getvalue(), "image/png")


def test_bomb_upload_gets_friendly_page_not_crash(client):
    scan_route._classifier_override = MockClassifier()
    buf = io.BytesIO()
    Image.new("1", (12000, 12000)).save(buf, "PNG")
    r = post_photo(client, "huge.png", data=buf.getvalue(), ctype="image/png")
    assert r.status_code == 422 and "too large" in r.text


def test_normal_phone_photo_still_works():
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(buf, "JPEG")
    assert prepare_image(buf.getvalue(), "image/jpeg").width == 1024


# ---------- usage limits ----------

def test_scan_limit_per_visitor(client):
    scan_route._classifier_override = MockClassifier()
    per_hour = POLICIES["scan"][0][0].hits
    for _ in range(per_hour):
        assert post_photo(client, "bottle.jpg").status_code == 200
    r = post_photo(client, "bottle.jpg")
    assert r.status_code == 429 and "scan limit" in r.text


def test_invalid_uploads_do_not_use_up_the_limit(client):
    scan_route._classifier_override = MockClassifier()
    for _ in range(POLICIES["scan"][0][0].hits + 5):
        assert post_photo(client, "x.jpg", data=b"not an image").status_code == 422
    assert post_photo(client, "bottle.jpg").status_code == 200


def test_site_wide_daily_cap():
    limiter = RateLimiter(MemoryCounter(), "p")
    cap = POLICIES["report"][1]

    class Req:
        def __init__(self, ip):
            self.headers = {"x-real-ip": ip}
            self.client = None

    msgs = [limiter.check(Req(f"10.0.{i // 250}.{i % 250}"), "report") for i in range(cap + 1)]
    assert msgs[:cap] == [None] * cap and msgs[-1] == SITE_CAP_MESSAGE


def test_login_attempts_are_limited(monkeypatch):
    deps._auth_override, deps._repo_override = FakeAuth(), InMemoryDonationRepo()
    try:
        c = TestClient(create_app())
        c.get("/account/login")
        tok = c.cookies.get("rl_csrf")
        codes = [c.post("/account/login", data={"email": "a@b.co", "password": "wrong-pass", "csrf_token": tok}).status_code
                 for _ in range(POLICIES["auth"][0][0].hits + 1)]
        assert codes[-1] == 429 and set(codes[:-1]) == {400}
    finally:
        deps._auth_override = deps._repo_override = None


def test_visitor_keys_are_hashed_not_raw_ips():
    class Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = None

    assert client_ip(Req()) == "203.0.113.7"
    key = visitor_key(Req(), "pepper")
    assert "203.0.113.7" not in key and len(key) == 32
    assert key != visitor_key(Req(), "other-pepper")


def test_supabase_counter_uses_rpc_and_falls_back(monkeypatch):
    seen = {}

    def fake(method, url, json=None, params=None, headers=None, timeout=None):
        seen.update(url=url, json=json, auth=headers.get("Authorization"))
        return httpx.Response(200, json=False)

    monkeypatch.setattr(httpx, "request", fake)
    counter = SupabaseCounter(SupabaseClient("https://x.supabase.co", "pub", "sec"), MemoryCounter())
    assert counter.hit("k", 5, 60) is False
    assert seen["url"].endswith("/rest/v1/rpc/hit_rate_limit") and seen["auth"] == "Bearer sec"
    assert seen["json"] == {"p_key": "k", "p_limit": 5, "p_window_seconds": 60}

    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "request", down)
    assert counter.hit("k", 1, 60) is True and counter.hit("k", 1, 60) is False  # in-memory fallback still limits


# ---------- errors and auth edges ----------

def test_unexpected_errors_show_friendly_page_without_details():
    app = create_app()

    @app.get("/boom-test")
    def boom():
        raise RuntimeError("secret internal detail sk-should-not-leak")

    r = TestClient(app, raise_server_exceptions=False).get("/boom-test")
    assert r.status_code == 500 and "Something went wrong on our side" in r.text
    assert "sk-should-not-leak" not in r.text and "Traceback" not in r.text


def test_tampered_session_cookie_is_ignored_and_cleared():
    deps._auth_override, deps._repo_override = FakeAuth(), InMemoryDonationRepo()
    try:
        c = TestClient(create_app())
        c.cookies.set("rl_session", "eyJhY2Nlc3NfdG9rZW4iOiJmb3JnZWQifQ==")
        r = c.get("/dashboard", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/account/login")
    finally:
        deps._auth_override = deps._repo_override = None


def test_forged_token_for_another_user_is_rejected():
    auth = FakeAuth()
    deps._auth_override, deps._repo_override = auth, InMemoryDonationRepo()
    try:
        c = TestClient(create_app())
        signup(c, "real@x.test")
        from reloop.database.supabase import Session
        from reloop.security import encode_session
        forged = Session(access_token="made-up-token", refresh_token="ref-nobody", expires_at=9999999999, user_id="x", email="x@x")
        c.cookies.set("rl_session", encode_session(forged))
        deps._VERIFIED.clear()
        assert c.get("/dashboard", follow_redirects=False).status_code == 303
    finally:
        deps._auth_override = deps._repo_override = None


def test_supabase_errors_never_echo_response_bodies(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(500, text="internal: password=hunter2"))
    with pytest.raises(SupabaseError) as e:
        SupabaseClient("https://x.supabase.co", "pub", "sec").rest("GET", "/donation_listings")
    assert "hunter2" not in str(e.value)


def test_health_exposes_no_values(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://secret-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_dontleak")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    get_settings.cache_clear()
    body = TestClient(create_app()).get("/api/health").text
    assert "secret-project" not in body and "dontleak" not in body and "boss@example.com" not in body
