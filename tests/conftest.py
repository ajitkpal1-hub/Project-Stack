"""Shared test setup: tests never read the developer's real .env or service env vars."""

from __future__ import annotations

import pytest

from reloop.config import Settings, get_settings

_SERVICE_VARS = (
    "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
    "EMBEDDING_PROVIDER", "EMBEDDING_API_KEY", "EMBEDDING_MODEL",
    "MAPS_API_KEY", "APP_ENV", "ADMIN_EMAILS",
)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in _SERVICE_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
