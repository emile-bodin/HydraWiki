from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings


def test_health_endpoints_do_not_contact_external_ai_services() -> None:
    settings = Settings(database_url="postgresql://db:5432/hydrawiki", qdrant_url="http://qdrant:6333")
    client = TestClient(create_app(settings))

    assert client.get("/health/live").json() == {
        "status": "ok",
        "service": "HydraWiki",
        "checks": {"process": "ok"},
    }
    assert client.get("/health/ready").json()["checks"] == {"configuration": "ok"}
    assert client.get("/health/ready").json()["configuration"] == {
        "embedding_max_concurrency": 2,
        "ingest_max_concurrency": 1,
        "generation_max_concurrency": 1,
    }
