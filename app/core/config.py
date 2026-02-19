from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_chat_id: str
    github_webhook_secret: str
    generic_webhook_token: str
    admin_api_key: str = ""
    admin_api_keys: str = ""  # CSV map: key:scope,key2:scope
    admin_api_keys_active: str = ""  # Rotation active scoped keys
    admin_api_keys_previous: str = ""  # Rotation previous scoped keys
    admin_key_rotation_grace_seconds: int = 604800  # 7 days
    admin_key_rotation_started_at: str = ""  # unix timestamp or ISO8601
    log_level: str = "INFO"

    # Security / Limits
    max_body_size: int = 1024 * 1024  # 1MB default
    telegram_retries: int = 2
    message_verbosity: str = "compact"  # compact | detailed

    # Idempotency (TTL in seconds)
    idempotency_ttl: int = 3600  # 1 hour
    failed_delivery_ttl: int = 604800  # 7 days

    # Storage backend settings
    storage_backend: str = "memory"  # memory | redis
    redis_url: str = "redis://redis:6379/0"
    redis_key_prefix: str = "webhook_bridge"

    # Outbound HTTP behavior
    http_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)

    # Circuit breaker settings
    circuit_breaker_threshold: int = 5  # Failures before opening
    circuit_breaker_timeout: int = 60   # Seconds before half-open

    # Rate limiting settings
    rate_limit_backend: str = "memory"  # memory | redis
    rate_limit_ip_per_minute: int = 10
    rate_limit_token_per_minute: int = 30
    rate_limit_admin_per_minute: int = 20

    # WebSocket admin stream hardening
    ws_connects_per_minute: int = 10
    ws_max_connections_per_ip: int = 3

    # Replay hardening
    replay_cooldown_seconds: int = 30
    max_replay_attempts: int = 10

    # Proxy / client IP extraction
    trusted_proxies: str = ""  # Comma-separated proxy IPs/CIDRs trusted for X-Forwarded-For

    # Network boundary controls for admin/replay/websocket endpoints
    admin_ip_allowlist: str = ""  # Comma-separated IPs/CIDRs; empty disables allowlist
    ws_ip_allowlist: str = ""  # Optional websocket-specific allowlist; falls back to admin_ip_allowlist

    # Multi-destination routing
    routes_yaml: str = ""  # Path to YAML routing config or inline YAML

    # Discord destination
    discord_webhook_url: str = ""

    # Slack destination
    slack_webhook_url: str = ""

    # GitHub App
    github_app_id: str = ""
    github_app_private_key: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def _empty_string_to_default_for_ints(cls, value, info):
        if value != "":
            return value
        field = cls.model_fields.get(info.field_name)
        if field is None or field.annotation is not int:
            return value
        return field.default

    @field_validator("message_verbosity", mode="before")
    @classmethod
    def _normalize_message_verbosity(cls, value):
        normalized = str(value or "compact").strip().lower()
        if normalized not in {"compact", "detailed"}:
            return "compact"
        return normalized

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
