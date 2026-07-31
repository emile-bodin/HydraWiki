"""Typed application configuration with fail-fast validation."""

from functools import lru_cache

from pydantic import AnyHttpUrl, AnyUrl, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration required by every HydraWiki backend process."""

    model_config = SettingsConfigDict(env_prefix="HYDRAWIKI_", env_file=".env", extra="ignore")

    app_name: str = Field(default="HydraWiki", min_length=1)
    api_host: str = Field(default="0.0.0.0", min_length=1)
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: AnyUrl
    qdrant_url: AnyHttpUrl
    local_repositories_root: str = "/repositories"
    workspace_root: str = "/var/lib/hydrawiki/workspaces"


@lru_cache
def get_settings() -> Settings:
    """Load settings once so startup and request handling share one validated value."""

    return Settings()


def validate_settings() -> Settings:
    """Validate configuration explicitly for API and worker startup."""

    try:
        return get_settings()
    except ValidationError as exc:
        raise RuntimeError(f"Invalid HydraWiki configuration: {exc}") from exc
