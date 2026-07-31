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


def liveness(settings: Settings) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, checks={"process": "ok"})


def readiness(settings: Settings) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        checks={"configuration": "ok"},
    )
