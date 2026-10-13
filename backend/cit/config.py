"""Process configuration from environment variables.

Secrets only ever come from the environment (or a Docker secret mounted as an
env file). Nothing in here is sent to the browser.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DISPLAY_TZ = ZoneInfo("Asia/Singapore")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CIT_", env_file=".env", extra="ignore")

    env: str = Field("development", description="development | test | production")

    # Privileged Postgres connection for workers (Supabase: use the session
    # pooler or direct connection string). Never exposed to the web tier.
    database_url: SecretStr = SecretStr("postgresql+psycopg://cit:cit@localhost:5432/cit")
    # Supabase's transaction pooler (port 6543) does not support prepared statements.
    database_disable_prepared_statements: bool = False

    log_level: str = "INFO"
    log_json: bool = True

    # Internal API: bound to the Docker network only; token required for
    # mutating endpoints called by the Next.js server.
    internal_api_token: SecretStr = SecretStr("")

    # Global outbound request ceiling across all providers (requests/minute).
    global_rate_limit_per_minute: int = 120
    http_timeout_seconds: float = 20.0
    user_agent: str = "CryptoIntelligenceTerminal/0.1 (private research; contact: operator)"

    # Optional provider credentials. All optional: features degrade without them.
    goplus_app_key: SecretStr | None = None
    goplus_app_secret: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_alert_chat_id: str | None = None
    alchemy_api_key: SecretStr | None = None
    helius_api_key: SecretStr | None = None

    # Public dashboard URL, used to turn app paths in alerts into links (e.g. https://cit.example.com).
    public_url: str | None = None

    # Scheduler master switch (lets the API container run without jobs).
    scheduler_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
