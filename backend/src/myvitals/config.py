from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "db"
    postgres_port: int = 5432

    ingest_token: str
    query_token: str

    log_level: str = "INFO"
    tz: str = "UTC"

    ha_url: str | None = None
    ha_token: str | None = None
    # Comma-separated HA entity IDs to poll into env_readings.
    # e.g. "sensor.bedroom_temperature,sensor.bedroom_humidity,binary_sensor.bedroom_presence"
    ha_entities: str = ""

    @property
    def ha_entity_list(self) -> list[str]:
        return [e.strip() for e in self.ha_entities.split(",") if e.strip()]

    # --- Strava integration ---
    strava_client_id: str | None = None
    strava_client_secret: str | None = None
    # Public callback URL Strava redirects to after the user authorises.
    # Should point at the dashboard (Caddy on :8080), which proxies /auth/* to
    # the backend. Strava's "Authorization Callback Domain" (no port) must
    # match the host of this URL.
    strava_callback_url: str = "http://localhost:8080/auth/strava/callback"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
