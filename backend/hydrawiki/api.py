"""FastAPI application and Phase-2 repository lifecycle endpoints."""

from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import Settings, validate_settings
from .health import HealthResponse, liveness, readiness
from .persistence import Database, RepositoryStore
from .sources import LocalRepositoryAdapter, PublicGitRepositoryAdapter, SourceValidationError


class RepositoryRegistration(BaseModel):
    source_type: Literal["local", "public_git"]
    path: str | None = Field(default=None, min_length=1)
    url: HttpUrl | None = None
    ref: str | None = None
    display_name: str = Field(min_length=1, max_length=200)


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: Literal["local", "public_git"]
    source_value: str
    selected_ref: str | None
    display_name: str
    lifecycle_status: Literal["registered", "deleting", "deleted", "delete_failed"]
    last_error: str | None


def store_for(settings: Settings) -> RepositoryStore:
    return RepositoryStore(Database(str(settings.database_url)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if getattr(_.state, "settings", None) is None:
        _.state.settings = validate_settings()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title=(settings.app_name if settings else "HydraWiki"), version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health/live", response_model=HealthResponse, tags=["health"])
    def health_live() -> HealthResponse:
        return liveness(app.state.settings or validate_settings())

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def health_ready() -> HealthResponse:
        return readiness(app.state.settings or validate_settings())

    @app.post("/api/repositories", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
    def register_repository(request: RepositoryRegistration) -> RepositoryResponse:
        current = app.state.settings or validate_settings()
        try:
            if request.source_type == "local":
                if request.path is None or request.url is not None or request.ref is not None:
                    raise SourceValidationError("local registration requires only a relative path")
                source = LocalRepositoryAdapter(Path(current.local_repositories_root), request.path)
                source_value, selected_ref = source.relative_path, None
            else:
                if request.url is None or request.ref is None or request.path is not None:
                    raise SourceValidationError("public Git registration requires URL and ref")
                source = PublicGitRepositoryAdapter(str(request.url), request.ref)
                source_value, selected_ref = source.url, source.selected_ref
            row = store_for(current).create(
                {
                    "id": uuid4(),
                    "source_type": request.source_type,
                    "source_value": source_value,
                    "selected_ref": selected_ref,
                    "display_name": request.display_name,
                }
            )
            return RepositoryResponse.model_validate(row)
        except SourceValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/repositories", response_model=list[RepositoryResponse])
    def list_repositories() -> list[RepositoryResponse]:
        current = app.state.settings or validate_settings()
        return [RepositoryResponse.model_validate(row) for row in store_for(current).list()]

    @app.get("/api/repositories/{repository_id}", response_model=RepositoryResponse)
    def get_repository(repository_id: UUID) -> RepositoryResponse:
        current = app.state.settings or validate_settings()
        row = store_for(current).get(repository_id)
        if row is None:
            raise HTTPException(status_code=404, detail="repository not found")
        return RepositoryResponse.model_validate(row)

    @app.delete("/api/repositories/{repository_id}", response_model=RepositoryResponse)
    def delete_repository(repository_id: UUID, response: Response) -> RepositoryResponse:
        current = app.state.settings or validate_settings()
        store = store_for(current)
        row = store.mark_deleting(repository_id)
        if row is None:
            raise HTTPException(status_code=404, detail="repository not found")
        workspace = Path(current.workspace_root).resolve() / str(repository_id)
        try:
            if workspace.is_symlink():
                raise RuntimeError("repository workspace must not be a symlink")
            if workspace.exists():
                if workspace.parent != Path(current.workspace_root).resolve() or not workspace.is_dir():
                    raise RuntimeError("repository workspace is not a safe managed directory")
                rmtree(workspace)
            store.delete_relational_data(repository_id)
        except Exception as exc:  # lifecycle must remain visible when cleanup is incomplete
            failed = store.mark_delete_failed(repository_id, str(exc))
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return RepositoryResponse.model_validate(failed)
        response.status_code = status.HTTP_200_OK
        return RepositoryResponse(
            id=repository_id,
            source_type=row["source_type"],
            source_value=row["source_value"],
            selected_ref=row["selected_ref"],
            display_name=row["display_name"],
            lifecycle_status="deleted",
            last_error=None,
        )

    return app


app = create_app()
