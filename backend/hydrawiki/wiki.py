"""Durable, citation-gated wiki generation from indexed source chunks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from psycopg.types.json import Jsonb

from .config import Settings
from .generation import GenerationError, OpenAICompatibleGenerationAdapter
from .persistence import Database


class WikiGenerationError(RuntimeError):
    pass


class Citation(BaseModel):
    path: str = Field(min_length=1)
    line_start: int = Field(gt=0)
    line_end: int = Field(gt=0)


class GeneratedDocument(BaseModel):
    content: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


@dataclass(frozen=True)
class WikiGenerationResult:
    run_id: UUID
    status: str
    error: str | None = None


class WikiStore:
    def __init__(self, database: Database):
        self.database = database

    def select_sources(self, repository_id: UUID, source_paths: list[str] | None, max_characters: int) -> list[dict]:
        self.database.migrate()
        with self.database.connection() as connection:
            query = "SELECT id, path, chunk_text, line_start, line_end FROM chunks WHERE repository_id = %s"
            parameters: list[object] = [repository_id]
            if source_paths:
                query += " AND path = ANY(%s)"
                parameters.append(source_paths)
            query += " ORDER BY path, ordinal"
            rows = list(connection.execute(query, parameters))
        selected: list[dict] = []
        total = 0
        for row in rows:
            size = len(row["chunk_text"])
            if selected and total + size > max_characters:
                break
            if size > max_characters:
                raise WikiGenerationError("an indexed source chunk exceeds the generation source limit")
            selected.append(row)
            total += size
        if not selected:
            raise WikiGenerationError("no indexed source chunks are available for generation")
        return selected

    def start(self, repository_id: UUID, page_path: str, source_selection: list[dict], settings: Settings) -> UUID:
        run_id = uuid4()
        compact_selection = [
            {"chunk_id": str(row["id"]), "path": row["path"], "line_start": row["line_start"], "line_end": row["line_end"]}
            for row in source_selection
        ]
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO generation_runs
                (id, repository_id, page_path, status, source_selection, generation_url, configured_model, prompt_version)
                VALUES (%s, %s, %s, 'running', %s, %s, %s, %s)""",
                (run_id, repository_id, page_path, Jsonb(compact_selection), str(settings.generation_url) if settings.generation_url else None, settings.generation_model, settings.generation_prompt_version),
            )
        return run_id

    def set_source_selection(self, run_id: UUID, source_selection: list[dict]) -> None:
        compact_selection = [
            {"chunk_id": str(row["id"]), "path": row["path"], "line_start": row["line_start"], "line_end": row["line_end"]}
            for row in source_selection
        ]
        with self.database.connection() as connection:
            connection.execute("UPDATE generation_runs SET source_selection = %s WHERE id = %s", (Jsonb(compact_selection), run_id))

    def add_artifact(self, run_id: UUID, artifact_type: str, content: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO generation_artifacts (id, generation_run_id, artifact_type, content) VALUES (%s, %s, %s, %s)",
                (uuid4(), run_id, artifact_type, content),
            )

    def fail(self, run_id: UUID, error: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE generation_runs SET status = 'failed', error = %s, completed_at = now() WHERE id = %s",
                (error[:2000], run_id),
            )

    def validate_citations(self, repository_id: UUID, citations: list[Citation], selection: list[dict]) -> None:
        allowed: dict[str, list[tuple[int, int]]] = {}
        for row in selection:
            allowed.setdefault(row["path"], []).append((row["line_start"], row["line_end"]))
        with self.database.connection() as connection:
            for citation in citations:
                if citation.line_end < citation.line_start:
                    raise WikiGenerationError("citation line range is invalid")
                source = connection.execute(
                    """SELECT cache.line_count FROM source_files source
                    JOIN content_cache cache ON cache.id = source.content_cache_id
                    WHERE source.repository_id = %s AND source.path = %s""",
                    (repository_id, citation.path),
                ).fetchone()
                if source is None or citation.line_end > source["line_count"]:
                    raise WikiGenerationError("citation does not reference an indexed source line range")
                intervals = sorted(allowed.get(citation.path, []))
                cursor = citation.line_start
                for start, end in intervals:
                    if start > cursor:
                        break
                    if end >= cursor:
                        cursor = end + 1
                    if cursor > citation.line_end:
                        break
                if cursor <= citation.line_end:
                    raise WikiGenerationError("citation is outside the selected indexed source ranges")

    def publish(self, run_id: UUID, repository_id: UUID, page_path: str, title: str, document: GeneratedDocument, provider_model: str) -> None:
        page_id = uuid4()
        with self.database.connection() as connection:
            with connection.transaction():
                existing = connection.execute(
                    "SELECT id FROM wiki_pages WHERE repository_id = %s AND path = %s",
                    (repository_id, page_path),
                ).fetchone()
                if existing is not None:
                    page_id = existing["id"]
                    connection.execute("DELETE FROM wiki_page_sources WHERE wiki_page_id = %s", (page_id,))
                    connection.execute(
                        """UPDATE wiki_pages SET title = %s, content = %s, generation_run_id = %s, updated_at = now()
                        WHERE id = %s""",
                        (title, document.content, run_id, page_id),
                    )
                else:
                    connection.execute(
                        """INSERT INTO wiki_pages (id, repository_id, path, title, content, lifecycle_status, generation_run_id)
                        VALUES (%s, %s, %s, %s, %s, 'published', %s)""",
                        (page_id, repository_id, page_path, title, document.content, run_id),
                    )
                for citation in document.citations:
                    connection.execute(
                        "INSERT INTO wiki_page_sources (wiki_page_id, repository_id, path, line_start, line_end) VALUES (%s, %s, %s, %s, %s)",
                        (page_id, repository_id, citation.path, citation.line_start, citation.line_end),
                    )
                connection.execute(
                    "UPDATE generation_runs SET status = 'succeeded', provider_model = %s, error = NULL, completed_at = now() WHERE id = %s",
                    (provider_model, run_id),
                )

    def get_run(self, run_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute("SELECT * FROM generation_runs WHERE id = %s", (run_id,)).fetchone()

    def list_pages(self, repository_id: UUID) -> list[dict]:
        self.database.migrate()
        with self.database.connection() as connection:
            return list(connection.execute("SELECT * FROM wiki_pages WHERE repository_id = %s ORDER BY path", (repository_id,)))

    def get_page(self, repository_id: UUID, path: str) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            page = connection.execute("SELECT * FROM wiki_pages WHERE repository_id = %s AND path = %s", (repository_id, path)).fetchone()
            if page is None:
                return None
            page["citations"] = list(connection.execute("SELECT path, line_start, line_end FROM wiki_page_sources WHERE wiki_page_id = %s ORDER BY path, line_start, line_end", (page["id"],)))
            return page


def _prompt(title: str, sources: list[dict]) -> str:
    excerpts = "\n\n".join(f"--- {row['path']}:{row['line_start']}-{row['line_end']} ---\n{row['chunk_text']}" for row in sources)
    return (
        "Write a factual Markdown wiki page titled '%s' using only the indexed source excerpts below. "
        "Return JSON only with exactly: content (non-empty string) and citations (non-empty array of objects with path, line_start, line_end). "
        "Every claim must be supported by at least one citation, and every citation must use the provided paths and line ranges.\n\n%s"
    ) % (title, excerpts)


def generate_wiki_page(database: Database, settings: Settings, repository_id: UUID, page_path: str, title: str, source_paths: list[str] | None = None) -> WikiGenerationResult:
    store = WikiStore(database)
    run_id: UUID | None = None
    try:
        run_id = store.start(repository_id, page_path, [], settings)
        sources = store.select_sources(repository_id, source_paths, settings.generation_max_source_characters)
        store.set_source_selection(run_id, sources)
        prompt = _prompt(title, sources)
        store.add_artifact(run_id, "prompt", prompt)
        if not settings.generation_url or not settings.generation_model:
            raise WikiGenerationError("generation adapter is not configured")
        api_key = settings.generation_api_key.get_secret_value() if settings.generation_api_key else None
        generated = OpenAICompatibleGenerationAdapter(str(settings.generation_url), settings.generation_model, api_key, settings.generation_timeout_seconds, settings.generation_max_output_tokens).generate(prompt)
        store.add_artifact(run_id, "response", generated.content)
        try:
            document = GeneratedDocument.model_validate(json.loads(generated.content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise WikiGenerationError("generation response did not contain a valid cited page") from exc
        store.validate_citations(repository_id, document.citations, sources)
        store.publish(run_id, repository_id, page_path, title, document, generated.model)
        return WikiGenerationResult(run_id, "succeeded")
    except (GenerationError, WikiGenerationError) as exc:
        error = str(exc)
    except Exception:
        error = "wiki page persistence failed"
    if run_id is not None:
        try:
            store.add_artifact(run_id, "validation_error", error)
            store.fail(run_id, error)
        except Exception:
            # A database outage cannot be masked as a successful publication.
            pass
    return WikiGenerationResult(run_id or uuid4(), "failed", error)
