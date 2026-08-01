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
