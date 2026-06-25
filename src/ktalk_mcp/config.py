import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB_PATH = "95_TRANSCRIPTS/.registry.db"


def resolve_db_path(cli_db: str | None = None) -> Path:
    """Resolve the registry DB path: --db flag > KTALK_REGISTRY_DB env > default."""
    if cli_db:
        return Path(cli_db)
    env = os.environ.get("KTALK_REGISTRY_DB")
    if env:
        return Path(env)
    return Path(DEFAULT_DB_PATH)


class Settings(BaseSettings):
    """KTalk MCP server configuration.

    Environment variables:
        KTALK_BASE_URL: KTalk instance URL (default: https://your-domain.ktalk.ru)
        KTALK_SESSION_TOKEN: Session token from browser cookies (required)
    """

    ktalk_base_url: str = "https://your-domain.ktalk.ru"
    ktalk_session_token: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
