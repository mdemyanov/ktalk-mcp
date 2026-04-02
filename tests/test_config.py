
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
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_BASE_URL", raising=False)

    from ktalk_mcp.config import Settings

    with pytest.raises(Exception):
        Settings()
