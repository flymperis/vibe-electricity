from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Static configuration from the environment / .env. The values marked
    'runtime' can also be changed on the Settings page (stored in the DB)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/vibe_electricity.db"

    # Paperless-ngx: API address as seen by this app, and the address your browser uses (for links)
    paperless_url: str = "http://localhost:8000"
    paperless_public_url: str = ""
    paperless_token: str = ""
    paperless_tag: str = "Electricity"  # runtime: documents with this tag are electricity bills

    # Ollama, used only for bills the built-in rules cannot read
    ollama_url: str = "http://localhost:11434"  # runtime
    ollama_model: str = "qwen3:8b"  # runtime
    llm_enabled: bool = True  # runtime

    sync_interval_minutes: int = 30  # runtime: poll Paperless (the webhook makes it instant)
    sync_on_startup: bool = True
    webhook_secret: str = ""  # if set, POST /api/webhook needs header X-Webhook-Secret
    timezone: str = "Europe/Athens"  # for times shown in the UI (stored in UTC)

    @property
    def public_paperless(self) -> str:
        return (self.paperless_public_url or self.paperless_url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
