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

    # aiohttp connector tuning — unlimited pool, DNS cache on.
    AIOHTTP_CONNECTOR_LIMIT: int = 0
    # Per-host idle pool cap. 0 = unlimited (matches AIOHTTP_CONNECTOR_LIMIT
    # default), but on bursty ramps it pays to bound it explicitly so the
    # event loop doesn't spin up an unbounded number of FDs and blow past
    # the soft `ulimit -n`.
    AIOHTTP_LIMIT_PER_HOST: int = 512
    AIOHTTP_DNS_TTL: int = 300
    # How long aiohttp keeps idle keep-alive connections in the pool. Default
    # is 15s — too short for k6 profile transitions (steady → pause → ramp);
    # idle sockets time out and the next wave pays a full TCP handshake.
    AIOHTTP_KEEPALIVE_TIMEOUT: float = 120.0
    # Socket-level TCP keepalive idle before the first probe. This mirrors
    # apigate's TCP_KEEPALIVE config on upstream sockets.
    AIOHTTP_TCP_KEEPALIVE_IDLE: int = 30

    # Timeouts. Connect budgets are aligned across auth/data and gateways;
    # auth keeps a tighter total budget because it is single-shot.
    UPSTREAM_CONNECT_TIMEOUT: float = 3.0
    UPSTREAM_TOTAL_TIMEOUT: float = 10.0
    AUTH_CONNECT_TIMEOUT: float = 3.0
    AUTH_TOTAL_TIMEOUT: float = 3.0


settings = Settings()
