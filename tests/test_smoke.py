"""Phase 1 smoke tests: the app boots, renders the home page, and reports health without leaking secrets."""

from fastapi.testclient import TestClient

from reloop.config import get_settings
from reloop.web import create_app


def client() -> TestClient:
    return TestClient(create_app())


def test_home_page_renders():
    response = client().get("/")
    assert response.status_code == 200
    assert "RELOOP AI" in response.text
    assert "Sort Smart. Reuse More. Waste Less." in response.text


def test_health_reports_ok():
    data = client().get("/api/health").json()
    assert data["status"] == "ok"
    assert data["python"].startswith("3.12")
    assert set(data["integrations"]) == {"supabase", "llm", "embeddings", "maps"}


def test_health_never_exposes_secret_values(monkeypatch):
    secret = "sk-test-should-never-appear"
    monkeypatch.setenv("LLM_PROVIDER", "test")
    monkeypatch.setenv("LLM_API_KEY", secret)
    get_settings.cache_clear()
    try:
        response = client().get("/api/health")
        assert secret not in response.text
        assert response.json()["integrations"]["llm"] is True
        assert secret not in client().get("/").text
    finally:
        get_settings.cache_clear()


def test_stylesheet_served_locally():
    response = client().get("/css/poc.css")
    assert response.status_code == 200
