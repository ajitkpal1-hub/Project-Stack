"""Browser tests: run the real app on a local port with fake services, drive it with Edge.

Skipped automatically when Playwright or the Edge browser isn't available, so the
normal test run never needs them. No network, no API keys, nothing stored.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")


@dataclass
class App:
    url: str
    auth: object
    donations: object
    partners: object
    dashboards: object
    geo: object


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge")
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Edge browser not available: {e}")
        yield b
        b.close()


@pytest.fixture
def app(monkeypatch):
    import uvicorn

    from reloop.config import get_settings
    from reloop.database.memory import InMemoryDashboardRepo, InMemoryDonationRepo, InMemoryPartnerRepo
    from reloop.routes import assistant as assistant_route
    from reloop.routes import deps
    from reloop.routes import scan as scan_route
    from reloop.services.classifier import MockClassifier
    from reloop.web import create_app
    from tests.test_donations import FakeAuth
    from tests.test_partners import FakeGeo

    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    get_settings.cache_clear()
    auth, drepo, prepo = FakeAuth(), InMemoryDonationRepo(), InMemoryPartnerRepo()
    dash, geo = InMemoryDashboardRepo(drepo, prepo), FakeGeo()
    monkeypatch.setattr(deps, "_auth_override", auth)
    monkeypatch.setattr(deps, "_repo_override", drepo)
    monkeypatch.setattr(deps, "_partner_repo_override", prepo)
    monkeypatch.setattr(deps, "_dash_repo_override", dash)
    monkeypatch.setattr(deps, "_geo_override", geo)
    monkeypatch.setattr(scan_route, "_classifier_override", MockClassifier())
    monkeypatch.setattr(assistant_route, "_assistant_override", None)
    deps._VERIFIED.clear()

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield App(f"http://127.0.0.1:{port}", auth, drepo, prepo, dash, geo)
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def new_page(browser):
    contexts = []

    def make(width: int = 390):
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        contexts.append(ctx)
        return ctx.new_page()

    yield make
    for ctx in contexts:
        ctx.close()
