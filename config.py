from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_chat_id: str
    github_webhook_secret: str
    generic_webhook_token: str
    log_level: str = "INFO"

    # Security / Limits
    max_body_size: int = 1024 * 1024  # 1MB default
    telegram_retries: int = 2

    # Idempotency (TTL in seconds)
    idempotency_ttl: int = 3600  # 1 hour

    # Circuit breaker settings
    circuit_breaker_threshold: int = 5  # Failures before opening
    circuit_breaker_timeout: int = 60   # Seconds before half-open

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
