from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings
from hydrawiki.health import HealthResponse, ReadinessError


def test_health_endpoints_verify_required_storage_but_not_external_ai_services(monkeypatch) -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
    monkeypatch.setattr(
        "hydrawiki.api.readiness",
        lambda _settings: HealthResponse(
            status="ok",
            service="HydraWiki",
            checks={"configuration": "ok", "database": "ok", "vectors": "ok"},
            configuration={"embedding_max_concurrency": 2, "ingest_max_concurrency": 1, "generation_max_concurrency": 1},
        ),
    )
    client = TestClient(create_app(settings))

    assert client.get("/health/live").json() == {
        "status": "ok",
        "service": "HydraWiki",
        "checks": {"process": "ok"},
    }
    assert client.get("/health/ready").json()["checks"] == {"configuration": "ok", "database": "ok", "vectors": "ok"}
    assert client.get("/health/ready").json()["configuration"] == {
        "embedding_max_concurrency": 2,
        "ingest_max_concurrency": 1,
        "generation_max_concurrency": 1,
    }


def test_readiness_failure_returns_503(monkeypatch) -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
    monkeypatch.setattr("hydrawiki.api.readiness", lambda _settings: (_ for _ in ()).throw(ReadinessError("required storage dependency is unavailable")))
    response = TestClient(create_app(settings)).get("/health/ready")
    assert response.status_code == 503
