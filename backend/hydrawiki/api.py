"""FastAPI application for the Phase-1 contract surface."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings, validate_settings
from .health import HealthResponse, liveness, readiness


@asynccontextmanager
async def lifespan(_: FastAPI):
    if getattr(_.state, "settings", None) is None:
        _.state.settings = validate_settings()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title=(settings.app_name if settings else "HydraWiki"), version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    def health_live() -> HealthResponse:
        return liveness(app.state.settings or validate_settings())

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def health_ready() -> HealthResponse:
        return readiness(app.state.settings or validate_settings())

    return app


app = create_app()
