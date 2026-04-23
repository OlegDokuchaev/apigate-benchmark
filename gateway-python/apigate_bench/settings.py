from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Upstream data-service (catalogue API).
    ORIGIN_BASE_URL: str = "http://127.0.0.1:8002"

    # auth-service /verify endpoint (full URL).
    AUTH_VERIFY_URL: str = "http://127.0.0.1:8001/verify"

    # Body limit for endpoints that buffer (search / lookup validation).
    MAX_BODY_BYTES: int = 1024 * 1024

    # aiohttp connector tuning — unlimited pool, DNS cache on.
    AIOHTTP_CONNECTOR_LIMIT: int = 0
    AIOHTTP_DNS_TTL: int = 300

    # Timeouts. Auth is on the request critical path, so a tighter budget.
    UPSTREAM_CONNECT_TIMEOUT: float = 3.0
    UPSTREAM_TOTAL_TIMEOUT: float = 10.0
    AUTH_CONNECT_TIMEOUT: float = 1.0
    AUTH_TOTAL_TIMEOUT: float = 3.0


settings = Settings()
