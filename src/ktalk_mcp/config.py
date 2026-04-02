from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """KTalk MCP server configuration.

    Environment variables:
        KTALK_BASE_URL: KTalk instance URL (default: https://your-domain.ktalk.ru)
        KTALK_SESSION_TOKEN: Session token from browser cookies (required)
    """

    ktalk_base_url: str = "https://your-domain.ktalk.ru"
    ktalk_session_token: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
