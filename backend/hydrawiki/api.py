"""FastAPI application and Phase-2 repository lifecycle endpoints."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import Settings, validate_settings
from .health import HealthResponse, ReadinessError, liveness, readiness
from .manifest import ManifestBusyError, ManifestStore, run_manifest
from .persistence import Database, RepositoryStore
from .sources import LocalRepositoryAdapter, PublicGitRepositoryAdapter, SourceValidationError
from .wiki import GenerationBusyError, WikiStore, generate_wiki_page
from .vectors import QdrantVectorStore


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
    last_successful_processing_at: datetime | None = None
    current_error: str | None = None


class ManifestRunResponse(BaseModel):
    id: UUID
    repository_id: UUID
    status: Literal["running", "succeeded", "failed"]
    parser_version: str
    file_count: int
    total_bytes: int
    error: str | None
    started_at: datetime
    completed_at: datetime | None
    phase: str = "Manifest"
    current_count: int = 0
    total_count: int = 0
    percentage: int = 0


class WikiGenerationRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    source_paths: list[str] | None = None


class CitationResponse(BaseModel):
    path: str
    line_start: int
    line_end: int


class MermaidDiagramResponse(BaseModel):
    ordinal: int
    source: str
    status: Literal["safe", "failed"]
    svg: str | None = None
    error: str | None = None


class WikiPageResponse(BaseModel):
    id: UUID
    path: str
    title: str
    content: str
    lifecycle_status: Literal["published"]
    generation_run_id: UUID
    citations: list[CitationResponse] = Field(default_factory=list)
    diagrams: list[MermaidDiagramResponse] = Field(default_factory=list)


class WikiPageSummaryResponse(BaseModel):
    path: str
    title: str
    lifecycle_status: Literal["published"]
    generation_run_id: UUID


class GenerationRunResponse(BaseModel):
    id: UUID
    repository_id: UUID
    page_path: str
    status: Literal["running", "succeeded", "failed"]
    source_selection: list[dict]
    configured_model: str | None
    provider_model: str | None
    prompt_version: str
    error: str | None
    failure_stage: str | None = None
    started_at: datetime
    completed_at: datetime | None
    diagrams: list[MermaidDiagramResponse] = Field(default_factory=list)


class IndexedSourceResponse(BaseModel):
    path: str
    content: str
    line_count: int


def store_for(settings: Settings) -> RepositoryStore:
    return RepositoryStore(Database(str(settings.database_url)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if getattr(_.state, "settings", None) is None:
        _.state.settings = validate_settings()
    database = Database(str(_.state.settings.database_url))
    database.migrate()
    database.verify_schema_compatible()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title=(settings.app_name if settings else "HydraWiki"), version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    @app.get("/health/live", response_model=HealthResponse, response_model_exclude_none=True, tags=["health"])
    def health_live() -> HealthResponse:
        return liveness(app.state.settings or validate_settings())

    @app.get("/health/ready", response_model=HealthResponse, tags=["health"])
    def health_ready() -> HealthResponse:
        try:
            return readiness(app.state.settings or validate_settings())
        except ReadinessError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

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

    @app.post("/api/repositories/{repository_id}/sync", response_model=ManifestRunResponse, status_code=status.HTTP_201_CREATED)
    def sync_repository(repository_id: UUID) -> ManifestRunResponse:
        current = app.state.settings or validate_settings()
        store = store_for(current)
        repository = store.get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="repository not found")
        try:
            result = run_manifest(store.database, current, repository)
        except ManifestBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        row = ManifestStore(store.database).get(result.run_id)
        assert row is not None
        return ManifestRunResponse.model_validate(row)

    @app.get("/api/ingestion-runs/{run_id}", response_model=ManifestRunResponse)
    def get_manifest_run(run_id: UUID) -> ManifestRunResponse:
        current = app.state.settings or validate_settings()
        row = ManifestStore(Database(str(current.database_url))).get(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="ingestion run not found")
        return ManifestRunResponse.model_validate(row)

    @app.get("/api/repositories/{repository_id}/ingestion-runs", response_model=list[ManifestRunResponse])
    def list_manifest_runs(repository_id: UUID) -> list[ManifestRunResponse]:
        current = app.state.settings or validate_settings()
        store = store_for(current)
        if store.get(repository_id) is None:
            raise HTTPException(status_code=404, detail="repository not found")
        return [ManifestRunResponse.model_validate(row) for row in store.list_manifest_runs(repository_id)]

    @app.get("/api/ingestion-runs/{run_id}/entries")
    def get_manifest_entries(run_id: UUID) -> list[dict]:
        current = app.state.settings or validate_settings()
        store = ManifestStore(Database(str(current.database_url)))
        if store.get(run_id) is None:
            raise HTTPException(status_code=404, detail="ingestion run not found")
        return store.entries(run_id)

    @app.post("/api/repositories/{repository_id}/pages", response_model=GenerationRunResponse, status_code=status.HTTP_201_CREATED)
    def generate_page(repository_id: UUID, request: WikiGenerationRequest) -> GenerationRunResponse:
        current = app.state.settings or validate_settings()
        database = Database(str(current.database_url))
        if RepositoryStore(database).get(repository_id) is None:
            raise HTTPException(status_code=404, detail="repository not found")
        try:
            result = generate_wiki_page(database, current, repository_id, request.path, request.title, request.source_paths)
        except GenerationBusyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        row = WikiStore(database).get_run(result.run_id)
        if row is None:
            # The storage failure remains truthful: no page was published.
            raise HTTPException(status_code=500, detail=result.error or "generation run could not be persisted")
        return GenerationRunResponse.model_validate(row)

    @app.get("/api/generation-runs/{run_id}", response_model=GenerationRunResponse)
    def get_generation_run(run_id: UUID) -> GenerationRunResponse:
        current = app.state.settings or validate_settings()
        row = WikiStore(Database(str(current.database_url))).get_run(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="generation run not found")
        return GenerationRunResponse.model_validate(row)

    @app.get("/api/repositories/{repository_id}/generation-runs", response_model=list[GenerationRunResponse])
    def list_generation_runs(repository_id: UUID) -> list[GenerationRunResponse]:
        current = app.state.settings or validate_settings()
        store = store_for(current)
        if store.get(repository_id) is None:
            raise HTTPException(status_code=404, detail="repository not found")
        return [GenerationRunResponse.model_validate(row) for row in store.list_generation_runs(repository_id)]

    @app.get("/api/repositories/{repository_id}/pages", response_model=list[WikiPageSummaryResponse])
    def list_wiki_pages(repository_id: UUID) -> list[WikiPageSummaryResponse]:
        current = app.state.settings or validate_settings()
        database = Database(str(current.database_url))
        if RepositoryStore(database).get(repository_id) is None:
            raise HTTPException(status_code=404, detail="repository not found")
        return [WikiPageSummaryResponse.model_validate(row) for row in WikiStore(database).list_pages(repository_id)]

    @app.get("/api/repositories/{repository_id}/sources/{source_path:path}", response_model=IndexedSourceResponse)
    def get_indexed_source(repository_id: UUID, source_path: str) -> IndexedSourceResponse:
        current = app.state.settings or validate_settings()
        row = store_for(current).get_indexed_source(repository_id, source_path)
        if row is None:
            raise HTTPException(status_code=404, detail="indexed source not found")
        return IndexedSourceResponse(path=row["path"], content=row["normalized_content"], line_count=row["line_count"])

    @app.get("/api/repositories/{repository_id}/pages/{page_path:path}", response_model=WikiPageResponse)
    def get_wiki_page(repository_id: UUID, page_path: str) -> WikiPageResponse:
        current = app.state.settings or validate_settings()
        row = WikiStore(Database(str(current.database_url))).get_page(repository_id, page_path)
        if row is None:
            raise HTTPException(status_code=404, detail="wiki page not found")
        return WikiPageResponse.model_validate(row)

    @app.delete("/api/repositories/{repository_id}", response_model=RepositoryResponse)
    def delete_repository(repository_id: UUID, response: Response) -> RepositoryResponse:
        current = app.state.settings or validate_settings()
        store = store_for(current)
        receipt = store.get_deletion_receipt(repository_id)
        if receipt is not None:
            return RepositoryResponse.model_validate({**receipt, "lifecycle_status": "deleted", "last_error": None})
        row = store.mark_deleting(repository_id)
        if row is None:
            raise HTTPException(status_code=404, detail="repository not found")
        workspace = Path(current.workspace_root).resolve() / str(repository_id)
        try:
            QdrantVectorStore(str(current.qdrant_url)).delete(store.vector_ids(repository_id))
            if workspace.is_symlink():
                raise RuntimeError("repository workspace must not be a symlink")
            if workspace.exists():
                if workspace.parent != Path(current.workspace_root).resolve() or not workspace.is_dir():
                    raise RuntimeError("repository workspace is not a safe managed directory")
                rmtree(workspace)
            receipt = store.complete_delete(row)
        except Exception as exc:  # lifecycle must remain visible when cleanup is incomplete
            failed = store.mark_delete_failed(repository_id, str(exc))
            response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
            return RepositoryResponse.model_validate(failed)
        response.status_code = status.HTTP_200_OK
        return RepositoryResponse.model_validate({**receipt, "lifecycle_status": "deleted", "last_error": None})

    return app


app = create_app()
