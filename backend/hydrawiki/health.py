"""Foundation health checks.

Phase 1 deliberately checks configuration and process liveness only. Database and
vector-store connectivity belongs to the persistence and indexing phases.
"""

from typing import Literal

from pydantic import BaseModel

from .config import Settings
from .persistence import Database
from .vectors import QdrantVectorStore


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    checks: dict[str, Literal["ok"]]
    configuration: dict[str, int] | None = None


def liveness(settings: Settings) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, checks={"process": "ok"})


class ReadinessError(RuntimeError):
    """A required HydraWiki-owned dependency is unavailable."""


def readiness(settings: Settings) -> HealthResponse:
    """Verify dependencies required to accept API work.

    External model providers remain operation-specific: they must not make the
    API unhealthy when generation is not configured, and adapter failures stay
    visible on the affected ingestion or generation run.
    """
    try:
        with Database(str(settings.database_url)).connection() as connection:
            connection.execute("SELECT 1")
        QdrantVectorStore(str(settings.qdrant_url))._request("GET", "/readyz")
    except Exception as exc:
        raise ReadinessError("required storage dependency is unavailable") from exc
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        checks={"configuration": "ok", "database": "ok", "vectors": "ok"},
        configuration={
            "embedding_max_concurrency": settings.embedding_max_concurrency,
            "ingest_max_concurrency": settings.ingest_max_concurrency,
            "generation_max_concurrency": settings.generation_max_concurrency,
        },
    )
