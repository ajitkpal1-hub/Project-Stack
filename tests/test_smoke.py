"""Smoke tests: the app boots, every page renders, and health never leaks secrets."""

import pytest
from fastapi.testclient import TestClient

from reloop.config import get_settings
from reloop.models.categories import LANES, WasteCategory
from reloop.routes.pages import PAGES
from reloop.web import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_home_has_brand_hero_and_ctas(client):
    html = client.get("/").text
    assert "RELOOP" in html
    assert "Sort Smart. Reuse More. Waste Less." in html
    assert "Don&#39;t throw it away." in html or "Don't throw it away." in html
    assert 'action="/scan"' in html and 'type="file"' in html
    assert 'href="/donate"' in html


def test_home_shows_every_lane_once_in_guide(client):
    html = client.get("/").text
    for lane in LANES:
        assert f'id="lane-{lane.category.value}"' in html


def test_demo_listings_are_labelled(client):
    html = client.get("/").text
    assert "Demonstration listings only" in html


SIGNED_IN_ONLY = {"dashboard", "admin"}
PUBLIC_NAV = ["/", "/scan", "/assistant", "/donate", "/donations", "/centres", "/account/login", "/account/signup"]


@pytest.mark.parametrize("page", [p for p in PAGES if p.slug not in SIGNED_IN_ONLY], ids=lambda p: p.slug)
def test_every_public_page_renders_with_nav(client, page):
    response = client.get(page.path)
    assert response.status_code == 200
    assert page.title in response.text
    if page.slug == "centres":  # the only page still waiting for its phase
        assert f"Arrives in Phase {page.phase}" in response.text
    for path in PUBLIC_NAV:
        assert f'href="{path}"' in response.text


@pytest.mark.parametrize("path", ["/dashboard", "/admin", "/account"])
def test_signed_in_pages_send_visitors_to_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/account/login?next=")


def test_current_page_marked_in_nav(client):
    html = client.get("/donate").text
    assert 'href="/donate" aria-current="page"' in html


def test_hazard_strip_on_every_page(client):
    for path in ["/"] + [p.path for p in PAGES]:
        assert "Never in the regular bin" in client.get(path).text


def test_lanes_cover_all_categories():
    assert {lane.category for lane in LANES} == set(WasteCategory)
    hazardous = {lane.category for lane in LANES if lane.hazard}
    assert {WasteCategory.HAZARDOUS, WasteCategory.MEDICAL, WasteCategory.E_WASTE} <= hazardous


def test_health_reports_ok(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["python"].startswith("3.12")
    assert set(data["integrations"]) == {"supabase", "llm", "embeddings", "maps", "accounts", "admins_configured", "anon_key_misconfigured"}


def test_health_never_exposes_secret_values(monkeypatch):
    secret = "sk-test-should-never-appear"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", secret)
    get_settings.cache_clear()
    try:
        c = TestClient(create_app())
        response = c.get("/api/health")
        assert secret not in response.text
        assert response.json()["integrations"]["llm"] is True
        assert secret not in c.get("/").text
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/css/site.css", "/fonts/mukta-400-latin.woff2", "/favicon.svg"])
def test_static_assets_served_locally(client, path):
    assert client.get(path).status_code == 200


def test_signed_out_nav_offers_login_not_admin(client):
    html = client.get("/").text
    for path in PUBLIC_NAV:
        assert f'href="{path}"' in html
    assert 'href="/admin"' not in html


def test_tagline_sits_in_hero(client):
    html = client.get("/").text
    assert 'class="hero-tagline"' in html
