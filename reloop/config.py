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
    embedding_provider: str = ""  # "voyage" | "hash" (tests/dev only) | empty
    embedding_api_key: str = ""
    embedding_model: str = ""  # defaults to voyage-4
    rag_top_k: int = 6
    rag_min_similarity: float = 0.35  # below this a passage is not treated as relevant
    osm_user_agent: str = ""  # identifies the app to OpenStreetMap; generic default, no personal details
    admin_emails: str = ""  # comma-separated; these accounts can use the admin queue
    voice_tool_secret: str = ""  # shared secret ElevenLabs sends in X-Reloop-Voice-Key; empty = voice API off

    @property
    def voice_tools_ready(self) -> bool:
        """The voice API stays off unless the shared secret is long enough to be hard to guess."""
        return len(self.voice_tool_secret.strip()) >= 32

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def anon_key_is_secret(self) -> bool:
        """The public-key slot must never hold the secret key: that would switch off row-level security."""
        anon = self.supabase_anon_key.strip()
        return bool(anon) and (anon.startswith("sb_secret_") or anon == self.supabase_service_role_key.strip())

    @property
    def accounts_ready(self) -> bool:
        if self.anon_key_is_secret:
            return False
        return bool(self.supabase_url.strip() and self.supabase_anon_key.strip() and self.supabase_service_role_key.strip())

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
            "supabase": bool(self.supabase_url.strip() and self.supabase_service_role_key.strip()),
            "llm": self.llm_mode == "mock" or bool(self.llm_mode == "anthropic" and self.llm_api_key.strip()),
            "embeddings": bool(self.embedding_provider.strip() and (self.embedding_api_key.strip() or self.embedding_provider.strip().lower() == "hash")),
            "accounts": self.accounts_ready,
            "admins_configured": bool(self.admin_email_set),
            "anon_key_misconfigured": self.anon_key_is_secret,
            "voice_tools": self.voice_tools_ready,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
