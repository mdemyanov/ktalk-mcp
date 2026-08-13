import os
from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DB_PATH = "95_TRANSCRIPTS/.registry.db"


class AuthMode(str, Enum):
    """Активный механизм авторизации клиента (ADR-003)."""

    SESSION = "session"
    API_KEY = "api_key"


class KTalkConfigError(Exception):
    """Ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN не заданы."""


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
        KTALK_SESSION_TOKEN: Session token from browser cookies
        KTALK_PERSONAL_API_KEY: Персональный API-ключ (ADR-003) — приоритетнее сессии

    Оба секретных поля опциональны на уровне модели (ADR-003): конструирование
    `Settings()` никогда не падает само по себе. Приоритет режима (ключ -> сессия ->
    явная ошибка) вычисляется лениво в `.auth_mode` — единственной точке, где
    отсутствие ОБЕИХ переменных становится `KTalkConfigError`.

    NFR-5 / security review (SEC-001): `ktalk_session_token`/`ktalk_personal_api_key`
    объявлены `Field(repr=False)` — pydantic по умолчанию печатает значения ВСЕХ полей
    в `repr(settings)`/`str(settings)` (в отличие от `AuthContext`, который уже маскирует
    себя явно), а это ровно тот текст, что мог бы случайно попасть в отладочный
    `print`/`logger.debug(settings)` или в текст будущего `ValidationError`.
    """

    ktalk_base_url: str = "https://your-domain.ktalk.ru"
    ktalk_session_token: str | None = Field(default=None, repr=False)
    ktalk_personal_api_key: str | None = Field(default=None, repr=False)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def auth_mode(self) -> AuthMode:
        if self.ktalk_personal_api_key:
            return AuthMode.API_KEY
        if self.ktalk_session_token:
            return AuthMode.SESSION
        raise KTalkConfigError(
            "Не задана ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN. "
            "Укажите одну из переменных (см. README)."
        )

    @property
    def auth_credential(self) -> str:
        # .auth_mode уже проверил, что хотя бы одно поле непустое.
        return self.ktalk_personal_api_key or self.ktalk_session_token or ""


def redact_secrets(text: str) -> str:
    """Барьер маскирования (NFR-5, ADR-003 «SecretRedactor», ранее спроектирован, но не
    вызывался ниоткуда — security review SEC-001).

    Ни `KTalkError`, ни `httpx`-обёртки этого проекта сегодня не строят текст ошибки из
    `request.url`/`request.headers`/`repr(request)` (проверено ревью) — секрет не должен
    появиться в тексте исключения. Это тем не менее последний рубеж на границе CLI: если
    секрет всё же попадёт в текст произвольного, не-`KTalkError`-исключения (например, из
    сторонней зависимости, которая не следует той же дисциплине), значение маскируется
    здесь перед печатью, а не полагается только на дисциплину каждого источника ошибки.
    """
    try:
        settings = Settings()
    except Exception:  # noqa: BLE001 - барьер не должен сам стать новым источником отказа
        return text
    for value in (settings.ktalk_personal_api_key, settings.ktalk_session_token):
        if value:
            text = text.replace(value, "***REDACTED***")
    return text
