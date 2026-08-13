from pathlib import Path

import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-token-123")
    monkeypatch.setenv("KTALK_BASE_URL", "https://custom.ktalk.ru")

    from ktalk_mcp.config import Settings

    settings = Settings()
    assert settings.ktalk_session_token == "test-token-123"
    assert settings.ktalk_base_url == "https://custom.ktalk.ru"


def test_settings_default_base_url(monkeypatch):
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "test-token-123")
    monkeypatch.delenv("KTALK_BASE_URL", raising=False)

    from ktalk_mcp.config import Settings

    settings = Settings()
    assert settings.ktalk_base_url == "https://your-domain.ktalk.ru"


def test_settings_requires_session_token(monkeypatch):
    """ADR-003: оба секретных поля Optional на уровне модели — Settings() больше не
    падает сама по себе. Ошибка конфигурации (KTalkConfigError) откладывается до
    обращения к `.auth_mode`, единственной точке приоритета ключ -> сессия -> ошибка.
    Обновлено по решению PM (см. at-design-personal-api-key.md, «Известные конфликты»)."""
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_BASE_URL", raising=False)

    from ktalk_mcp.config import KTalkConfigError, Settings

    settings = Settings()  # не поднимает исключение
    with pytest.raises(KTalkConfigError):
        _ = settings.auth_mode


def test_resolve_db_path_default(monkeypatch):
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    from ktalk_mcp.config import DEFAULT_DB_PATH, resolve_db_path

    assert resolve_db_path() == Path(DEFAULT_DB_PATH)


def test_resolve_db_path_env(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_mcp.config import resolve_db_path

    assert resolve_db_path() == Path("/tmp/from-env.db")


def test_resolve_db_path_flag_wins(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_mcp.config import resolve_db_path

    assert resolve_db_path("/tmp/from-flag.db") == Path("/tmp/from-flag.db")
