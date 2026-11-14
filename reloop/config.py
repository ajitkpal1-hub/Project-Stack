"""Application settings, read from environment variables (never hardcoded)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    # Filled in later phases. Empty means "not configured yet".
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    llm_provider: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_provider: str = ""
    embedding_model: str = ""
    maps_api_key: str = ""

    @property
    def llm_mode(self) -> str:
        """LLM_PROVIDER normalised: tolerant of stray quotes, spaces and capitals."""
        return self.llm_provider.strip().strip("\"'").strip().lower()

    def llm_diagnostics(self) -> dict[str, object]:
        """Safe to expose: never echoes an unrecognised value (it could be a misplaced key)."""
        mode = self.llm_mode
        known = {"anthropic", "mock"}
        return {
            "provider": mode if mode in known else ("unset" if not mode else f"unrecognised ({len(mode)} chars)"),
            "api_key_present": bool(self.llm_api_key.strip()),
            "model_override": bool(self.llm_model.strip()),
        }

    def integration_status(self) -> dict[str, bool]:
        """Which integrations have credentials set. Reports booleans only, never values."""
        return {
            "supabase": bool(self.supabase_url and self.supabase_anon_key),
            "llm": self.llm_mode == "mock" or bool(self.llm_mode == "anthropic" and self.llm_api_key.strip()),
            "embeddings": bool(self.embedding_provider),
            "maps": bool(self.maps_api_key),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
