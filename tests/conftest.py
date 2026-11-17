"""Shared test setup: tests never read the developer's real .env or service env vars."""

from __future__ import annotations

import pytest

from reloop.config import Settings, get_settings

_SERVICE_VARS = (
    "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
    "EMBEDDING_PROVIDER", "EMBEDDING_API_KEY", "EMBEDDING_MODEL",
    "OSM_USER_AGENT", "APP_ENV", "ADMIN_EMAILS", "VOICE_TOOL_SECRET",
)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _SERVICE_VARS:
        monkeypatch.delenv(name, raising=False)
    from reloop.routes import deps
    from reloop.services.ratelimit import MemoryCounter, RateLimiter
    monkeypatch.setattr(deps, "_geo_disabled", True)
    monkeypatch.setattr(deps, "_limiter_override", RateLimiter(MemoryCounter(), "test-pepper"))  # fresh limits per test
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
