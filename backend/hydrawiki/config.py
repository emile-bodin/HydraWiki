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
    ollama_url: AnyHttpUrl = "http://ollama:11434"
    embedding_model: str = Field(default="nomic-embed-text:latest", min_length=1)
    embedding_index_version: str = Field(default="embedding-v1", min_length=1)
    embedding_timeout_seconds: float = Field(default=30, gt=0, le=300)
    embedding_max_concurrency: int = Field(default=2, ge=1, le=2)
    chunker_version: str = Field(default="line-v1", min_length=1)
    chunk_max_lines: int = Field(default=80, gt=0, le=1000)
    local_repositories_root: str = "/repositories"
    workspace_root: str = "/var/lib/hydrawiki/workspaces"
    max_repository_size_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)
    max_total_indexable_text_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_source_files: int = Field(default=25_000, gt=0)
    max_source_file_size_bytes: int = Field(default=2 * 1024 * 1024, gt=0)


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
