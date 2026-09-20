from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://swms:swms@localhost:5432/swms"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    environment: str = "development"

    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "swms_minio"
    minio_secret_key: str = "swms_minio_secret"
    minio_bucket: str = "swms-uploads"
    # False for the local docker-compose MinIO (plain HTTP); a real deploy
    # behind TLS sets this true via .env.
    minio_secure: bool = False

    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB, PDD-11

    # EXT-05 (LLM provider): optional by design. None (the default, and
    # .env.example's placeholder) means module M15's deterministic
    # keyword/regex matcher answers every question instead — the feature
    # must fully demonstrate offline. Set this in .env to turn on real
    # intent extraction and prose polishing via the Anthropic API.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5-20251001"


settings = Settings()
