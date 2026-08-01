import pytest
from pydantic import ValidationError

from hydrawiki.config import Settings


def test_required_service_urls_are_typed() -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
    assert str(settings.qdrant_url) == "http://qdrant:6333/"


def test_missing_required_configuration_fails() -> None:
    with pytest.raises(ValidationError, match="database_url|qdrant_url"):
        Settings()


def test_invalid_port_fails() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333", api_port=0)


def test_generation_adapter_configuration_is_optional_and_has_no_default_provider() -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
    assert settings.generation_url is None
    assert settings.generation_model is None
    assert Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333", generation_url="", generation_model="").generation_url is None


def test_workload_limits_use_typed_defaults() -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")

    assert settings.max_repository_size_bytes == 1024 * 1024 * 1024
    assert settings.max_source_files == 25_000
    assert settings.embedding_max_concurrency == 2


def test_workload_limits_accept_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES", "4096")
    monkeypatch.setenv("HYDRAWIKI_MAX_SOURCE_FILES", "12")
    monkeypatch.setenv("HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY", "1")

    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")

    assert settings.max_repository_size_bytes == 4096
    assert settings.max_source_files == 12
    assert settings.embedding_max_concurrency == 1


@pytest.mark.parametrize(
    ("variable", "value", "field"),
    [
        ("HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES", "0", "max_repository_size_bytes"),
        ("HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES", "", "max_repository_size_bytes"),
        ("HYDRAWIKI_MAX_SOURCE_FILES", "0", "max_source_files"),
        ("HYDRAWIKI_MAX_SOURCE_FILES", "", "max_source_files"),
        ("HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY", "3", "embedding_max_concurrency"),
        ("HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY", "", "embedding_max_concurrency"),
    ],
)
def test_invalid_workload_limit_environment_values_fail_validation(monkeypatch: pytest.MonkeyPatch, variable: str, value: str, field: str) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match=field):
        Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
