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

    def integration_status(self) -> dict[str, bool]:
        """Which integrations have credentials set. Reports booleans only, never values."""
        return {
            "supabase": bool(self.supabase_url and self.supabase_anon_key),
            "llm": bool(self.llm_provider and self.llm_api_key),
            "embeddings": bool(self.embedding_provider),
            "maps": bool(self.maps_api_key),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
