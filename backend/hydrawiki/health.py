"""Foundation health checks.

Phase 1 deliberately checks configuration and process liveness only. Database and
vector-store connectivity belongs to the persistence and indexing phases.
"""

from typing import Literal

from pydantic import BaseModel

from .config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    checks: dict[str, Literal["ok"]]
    configuration: dict[str, int] | None = None


def liveness(settings: Settings) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, checks={"process": "ok"})


def readiness(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        checks={"configuration": "ok"},
        configuration={
            "embedding_max_concurrency": settings.embedding_max_concurrency,
            "ingest_max_concurrency": settings.ingest_max_concurrency,
            "generation_max_concurrency": settings.generation_max_concurrency,
        },
    )
