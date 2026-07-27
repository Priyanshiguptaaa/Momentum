"""Application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_URL = f"sqlite:///{ROOT_DIR / 'data' / 'processed' / 'health_coach.db'}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HC_", env_file=".env", extra="ignore")

    database_url: str = DEFAULT_DB_URL
    default_user_email: str = "demo@healthcoach.local"
    default_user_name: str = "Demo User"
    calorie_target: float = 1700.0  # seed default only; prefer users.calorie_target
    lookback_days: int = 14
    # Shared secret for Health Auto Export → POST /sync/health-auto-export
    # Leave empty only for local prototyping on a trusted network.
    sync_api_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Hevy Pro developer key from https://hevy.com/settings?developer
    hevy_api_key: str = ""
    # Optional nightly Hevy auto-sync (server local time).
    hevy_auto_sync_enabled: bool = False
    hevy_auto_sync_hour: int = 2
    hevy_auto_sync_minute: int = 0
    # llm = model debates from evidence pack; statistical = rule engine only
    reasoning_mode: str = "llm"


settings = Settings()
