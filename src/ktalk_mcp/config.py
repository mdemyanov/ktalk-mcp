import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from ktalk_mcp.host_config import HostConfig


class AuthMode(str, Enum):
    """Активный механизм авторизации клиента (ADR-003)."""

    SESSION = "session"
    API_KEY = "api_key"


class KTalkConfigError(Exception):
    """Ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN не заданы."""


def resolve_db_path(
    cli_db: str | None = None, host_config: "HostConfig | None" = None
) -> Path:
    """Resolve the registry DB path (ADR-013 §3, расширено волной 3):

    `--db` > `KTALK_REGISTRY_DB` > `host_config.registry.db_path` (SA-003,
    discovery выполняется вызывающей стороной — `resolve_db_path` только
    использует уже готовый `HostConfig`) > машинный дефолт централизованного
    хранилища (`store.resolve_store_root`, FR-22).

    Старый относительный дефолт `95_TRANSCRIPTS/.registry.db` (ADR-002) заменён
    машинным дефолтом вне cwd (ADR-013) — единственный оставшийся источник
    относительного пути в этой функции теперь `host_config`, если проект-хозяин
    явно объявляет относительный `registry.db_path`.

    Code review (epic-capability-pairing, Р4): `warn_if_sync_dir` (NFR-14 AC-2)
    обязана применяться к итоговому пути независимо от источника (ADR-013-spec
    §«Поток данных» п.4) — до этой правки вызывалась только в ветке машинного
    дефолта; `--db`/`KTALK_REGISTRY_DB`/конфиг хозяина возвращали путь раньше.
    """
    from ktalk_mcp.store import resolve_store_root, warn_if_sync_dir

    if cli_db:
        path = Path(cli_db)
        warn_if_sync_dir(path)
        return path
    env = os.environ.get("KTALK_REGISTRY_DB")
    if env:
        path = Path(env)
        warn_if_sync_dir(path)
        return path
    if host_config is not None:
        configured = host_config.registry.get("db_path")
        if configured:
            path = Path(configured)
            warn_if_sync_dir(path)
            return path

    path = resolve_store_root() / "registry.db"
    warn_if_sync_dir(path)
    return path


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

    @model_validator(mode="after")
    def _fall_back_to_token_file(self) -> "Settings":
        """Третий источник сессии — файл `~/.config/ktalk-mcp/token` (token_file.py).

        Подставляется здесь, а не в `.auth_mode`, чтобы у файла и у переменной
        окружения была ровно одна точка входа в модель: всё остальное (приоритет
        ключа, `auth_credential`, барьер маскирования `redact_secrets`) продолжает
        читать одно поле и о существовании файла не знает.

        Порядок источников: `KTALK_PERSONAL_API_KEY` > `KTALK_SESSION_TOKEN` > файл.
        Файл читается только когда пусты ОБЕ переменные — заданное окружение
        сильнее лежащего на диске, иначе протухший файл молча перебивал бы токен,
        который оператор передал явно.
        """
        if self.ktalk_personal_api_key or self.ktalk_session_token:
            return self
        from ktalk_mcp.token_file import read_token

        token = read_token()
        if token:
            object.__setattr__(self, "ktalk_session_token", token)
        return self

    @property
    def auth_mode(self) -> AuthMode:
        if self.ktalk_personal_api_key:
            return AuthMode.API_KEY
        if self.ktalk_session_token:
            return AuthMode.SESSION
        raise KTalkConfigError(
            "Не задана ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN, "
            "и файла токена нет. Задайте переменную или выполните "
            "`ktalk token set -` (см. README)."
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
