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

    # EXT-01/EXT-03 (automation module): all three default to the free,
    # keyless public endpoints, so auto-populate works out of the box.
    # Override with a commercial/high-rate-tier URL or add an API key in
    # .env without any code change — app/automation/service.py reads these
    # settings, never a hardcoded URL.
    open_meteo_api_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_api_key: str | None = None
    overpass_api_url: str = "https://overpass-api.de/api/interpreter"
    open_elevation_api_url: str = "https://api.open-elevation.com/api/v1/lookup"
    geocoding_api_url: str = "https://nominatim.openstreetmap.org/search"


settings = Settings()
