"""Durable, citation-gated wiki generation from indexed source chunks."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from psycopg.types.json import Jsonb

from .config import Settings
from .generation import GenerationError, OpenAICompatibleGenerationAdapter
from .mermaid import MermaidError, MermaidRenderer, extract_mermaid_sources
from .persistence import Database


logger = logging.getLogger(__name__)


class WikiGenerationError(RuntimeError):
    pass


_PROMPT_PLACEHOLDERS = ("__TITLE__", "__SOURCE_EXCERPTS__")

WIKI_GROUPS = (
    ("get-started", "Get started"),
    ("concepts", "Concepts"),
    ("guides", "Guides"),
    ("reference", "Reference"),
    ("workflows", "Workflows"),
)
WIKI_GROUP_KEYS = {key for key, _label in WIKI_GROUPS}


class GenerationBusyError(WikiGenerationError):
    """The configured global wiki-generation limit has been reached."""


@contextmanager
def generation_slot(database: Database, slots: int):
    """Acquire a non-queuing global generation slot shared by API processes."""
    with database.connection() as connection:
        slot = None
        for candidate in range(slots):
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext('hydrawiki.wiki-generation') + %s) AS acquired",
                (candidate,),
            ).fetchone()["acquired"]
            if acquired:
                slot = candidate
                break
        if slot is None:
            raise GenerationBusyError("generation concurrency limit reached")
        try:
            yield
        finally:
            connection.execute("SELECT pg_advisory_unlock(hashtext('hydrawiki.wiki-generation') + %s)", (slot,))


class Citation(BaseModel):
    path: str = Field(min_length=1)
    line_start: int = Field(gt=0)
    line_end: int = Field(gt=0)


class GeneratedDocument(BaseModel):
    content: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class PlannedPage(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)


class WikiStructureGroup(BaseModel):
    key: str
    title: str
    pages: list[PlannedPage] = Field(default_factory=list)


class GeneratedPage(GeneratedDocument):
    group: str
    path: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)


class GeneratedWiki(BaseModel):
    structure: list[WikiStructureGroup] = Field(min_length=len(WIKI_GROUPS), max_length=len(WIKI_GROUPS))
    pages: list[GeneratedPage]


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

    def set_structure(self, run_id: UUID, structure: list[WikiStructureGroup]) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE generation_runs SET wiki_structure = %s WHERE id = %s",
                (Jsonb([group.model_dump() for group in structure]), run_id),
            )

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

    def fail(self, run_id: UUID, error: str, failure_stage: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE generation_runs SET status = 'failed', error = %s, failure_stage = %s, completed_at = now() WHERE id = %s",
                (error[:2000], failure_stage, run_id),
            )

    def add_diagram(self, run_id: UUID, ordinal: int, source: str, status: str, svg: str | None = None, error: str | None = None, page_path: str | None = None) -> None:
        with self.database.connection() as connection:
            connection.execute("INSERT INTO generation_diagrams (id, generation_run_id, ordinal, source, status, svg, error, page_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (uuid4(), run_id, ordinal, source, status, svg, error, page_path))

    def validate_mermaid(self, run_id: UUID, page_path: str, content: str, settings: Settings, ordinal: int) -> int:
        renderer = MermaidRenderer(settings.mermaid_renderer_command, settings.mermaid_timeout_seconds, settings.mermaid_max_source_characters, settings.mermaid_max_svg_bytes, settings.mermaid_renderer_user)
        for source in extract_mermaid_sources(content):
            try:
                rendered = renderer.render(source)
            except MermaidError as exc:
                self.add_diagram(run_id, ordinal, source, "failed", error=str(exc), page_path=page_path)
                raise WikiGenerationError(str(exc)) from exc
            self.add_diagram(run_id, ordinal, source, "safe", svg=rendered.svg, page_path=page_path)
            ordinal += 1
        return ordinal

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

    def publish(self, run_id: UUID, repository_id: UUID, pages: list[GeneratedPage], provider_model: str) -> None:
        with self.database.connection() as connection:
            with connection.transaction():
                paths = [page.path for page in pages]
                if paths:
                    connection.execute("DELETE FROM wiki_pages WHERE repository_id = %s AND NOT (path = ANY(%s))", (repository_id, paths))
                else:
                    connection.execute("DELETE FROM wiki_pages WHERE repository_id = %s", (repository_id,))
                for order, page in enumerate(pages):
                    existing = connection.execute("SELECT id FROM wiki_pages WHERE repository_id = %s AND path = %s", (repository_id, page.path)).fetchone()
                    page_id = existing["id"] if existing else uuid4()
                    if existing:
                        connection.execute("DELETE FROM wiki_page_sources WHERE wiki_page_id = %s", (page_id,))
                        connection.execute(
                            """UPDATE wiki_pages SET title = %s, content = %s, navigation_group = %s, navigation_order = %s, generation_run_id = %s, updated_at = now()
                            WHERE id = %s""",
                            (page.title, page.content, page.group, order, run_id, page_id),
                        )
                    else:
                        connection.execute(
                            """INSERT INTO wiki_pages (id, repository_id, path, title, content, lifecycle_status, generation_run_id, navigation_group, navigation_order)
                            VALUES (%s, %s, %s, %s, %s, 'published', %s, %s, %s)""",
                            (page_id, repository_id, page.path, page.title, page.content, run_id, page.group, order),
                        )
                    for citation in page.citations:
                        connection.execute(
                            "INSERT INTO wiki_page_sources (wiki_page_id, repository_id, path, line_start, line_end) VALUES (%s, %s, %s, %s, %s)",
                            (page_id, repository_id, citation.path, citation.line_start, citation.line_end),
                        )
                connection.execute(
                    "UPDATE generation_runs SET status = 'succeeded', provider_model = %s, error = NULL, failure_stage = NULL, completed_at = now() WHERE id = %s",
                    (provider_model, run_id),
                )

    def get_run(self, run_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            run = connection.execute("SELECT * FROM generation_runs WHERE id = %s", (run_id,)).fetchone()
            if run is not None:
                run["diagrams"] = list(connection.execute("SELECT ordinal, source, status, svg, error FROM generation_diagrams WHERE generation_run_id = %s ORDER BY ordinal", (run_id,)))
            return run

    def list_pages(self, repository_id: UUID) -> list[dict]:
        self.database.migrate()
        with self.database.connection() as connection:
            return list(connection.execute("SELECT path, title, lifecycle_status, generation_run_id FROM wiki_pages WHERE repository_id = %s ORDER BY navigation_order, path", (repository_id,)))

    def get_page(self, repository_id: UUID, path: str) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            page = connection.execute("SELECT * FROM wiki_pages WHERE repository_id = %s AND path = %s", (repository_id, path)).fetchone()
            if page is None:
                return None
            page["citations"] = list(connection.execute("SELECT path, line_start, line_end FROM wiki_page_sources WHERE wiki_page_id = %s ORDER BY path, line_start, line_end", (page["id"],)))
            page["group"] = page["navigation_group"]
            page["diagrams"] = list(connection.execute("SELECT ordinal, source, status, svg, error FROM generation_diagrams WHERE generation_run_id = %s AND (page_path = %s OR page_path IS NULL) ORDER BY ordinal", (page["generation_run_id"], path)))
            return page


def _load_prompt_template() -> str:
    try:
        return resources.files("hydrawiki.prompts").joinpath("wiki-v2.txt").read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError, UnicodeError) as exc:
        raise WikiGenerationError("wiki-v2 prompt template could not be loaded") from exc


def _prompt(title: str, sources: list[dict]) -> str:
    excerpts = "\n\n".join(f"--- {row['path']}:{row['line_start']}-{row['line_end']} ---\n{row['chunk_text']}" for row in sources)
    template = _load_prompt_template()
    missing = [placeholder for placeholder in _PROMPT_PLACEHOLDERS if placeholder not in template]
    if missing:
        raise WikiGenerationError(f"wiki-v2 prompt template is missing required placeholder(s): {', '.join(missing)}")
    return template.replace("__TITLE__", title).replace("__SOURCE_EXCERPTS__", excerpts)


def _wiki_prompt(sources: list[dict]) -> str:
    excerpts = "\n\n".join(f"--- {row['path']}:{row['line_start']}-{row['line_end']} ---\n{row['chunk_text']}" for row in sources)
    template = _load_prompt_template()
    if "__SOURCE_EXCERPTS__" not in template:
        raise WikiGenerationError("wiki-v2 prompt template is missing required placeholder(s): __SOURCE_EXCERPTS__")
    return template.replace("__TITLE__", "Repository wiki").replace("__SOURCE_EXCERPTS__", excerpts)


def _validate_structure(wiki: GeneratedWiki) -> None:
    expected = {key: label for key, label in WIKI_GROUPS}
    actual = {group.key: group for group in wiki.structure}
    if [group.key for group in wiki.structure] != [key for key, _label in WIKI_GROUPS] or len(actual) != len(wiki.structure):
        raise WikiGenerationError("generation response did not contain the five required wiki groups")
    for key, label in expected.items():
        if actual[key].title != label:
            raise WikiGenerationError(f"generation response changed the fixed wiki group label: {key}")
    planned: dict[str, tuple[str, str]] = {}
    for group in wiki.structure:
        for page in group.pages:
            if page.path in planned or not page.path.startswith(f"{group.key}/"):
                raise WikiGenerationError("generation response contained an invalid or duplicate planned page")
            planned[page.path] = (group.key, page.title)
    if len({page.path for page in wiki.pages}) != len(wiki.pages) or {page.path for page in wiki.pages} != set(planned):
        raise WikiGenerationError("generation response pages did not match the derived wiki structure")
    if any(page.group not in WIKI_GROUP_KEYS or planned[page.path] != (page.group, page.title) for page in wiki.pages):
        raise WikiGenerationError("generation response page metadata did not match the derived wiki structure")


def _parse_generated_wiki(content: str, legacy_path: str, legacy_title: str) -> GeneratedWiki:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise WikiGenerationError("generation response did not contain a valid wiki structure") from exc
    try:
        wiki = GeneratedWiki.model_validate(payload)
    except ValidationError:
        # Keep the pre-HYDWIK-25 function contract readable for old callers;
        # the operator endpoint no longer supplies a page path or title.
        try:
            document = GeneratedDocument.model_validate(payload)
        except ValidationError as exc:
            raise WikiGenerationError("generation response did not contain a valid cited wiki") from exc
        wiki = GeneratedWiki(
            structure=[WikiStructureGroup(key=key, title=label, pages=[PlannedPage(path=legacy_path, title=legacy_title)]) if key == "get-started" else WikiStructureGroup(key=key, title=label) for key, label in WIKI_GROUPS],
            pages=[GeneratedPage(group="get-started", path=legacy_path, title=legacy_title, content=document.content, citations=document.citations)],
        )
        return wiki
    _validate_structure(wiki)
    return wiki


def _deduplicate_citations(citations: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, int, int]] = set()
    unique: list[Citation] = []
    for citation in citations:
        key = (citation.path, citation.line_start, citation.line_end)
        if key not in seen:
            seen.add(key)
            unique.append(citation)
    return unique


def generate_wiki_page(database: Database, settings: Settings, repository_id: UUID, page_path: str, title: str, source_paths: list[str] | None = None) -> WikiGenerationResult:
    with generation_slot(database, settings.generation_max_concurrency):
        return _generate_wiki_page(database, settings, repository_id, page_path, title, source_paths)


def _generate_wiki_page(database: Database, settings: Settings, repository_id: UUID, page_path: str, title: str, source_paths: list[str] | None = None) -> WikiGenerationResult:
    store = WikiStore(database)
    run_id: UUID | None = None
    failure_stage = "start"
    try:
        run_id = store.start(repository_id, "wiki", [], settings)
        failure_stage = "source_selection"
        sources = store.select_sources(repository_id, source_paths, settings.generation_max_source_characters)
        store.set_source_selection(run_id, sources)
        failure_stage = "prompt"
        prompt = _wiki_prompt(sources)
        store.add_artifact(run_id, "prompt", prompt)
        if not settings.generation_url or not settings.generation_model:
            raise WikiGenerationError("generation adapter is not configured")
        api_key = settings.generation_api_key.get_secret_value() if settings.generation_api_key else None
        failure_stage = "generation"
        generated = OpenAICompatibleGenerationAdapter(str(settings.generation_url), settings.generation_model, api_key, settings.generation_timeout_seconds, settings.generation_max_output_tokens).generate(prompt)
        store.add_artifact(run_id, "response", generated.content)
        failure_stage = "response_validation"
        try:
            wiki = _parse_generated_wiki(generated.content, page_path, title)
        except WikiGenerationError:
            raise
        for page in wiki.pages:
            page.citations = _deduplicate_citations(page.citations)
        store.set_structure(run_id, wiki.structure)
        failure_stage = "citation_validation"
        for page in wiki.pages:
            store.validate_citations(repository_id, page.citations, sources)
        failure_stage = "mermaid_validation"
        diagram_ordinal = 0
        for page in wiki.pages:
            diagram_ordinal = store.validate_mermaid(run_id, page.path, page.content, settings, diagram_ordinal)
        failure_stage = "publication"
        store.publish(run_id, repository_id, wiki.pages, generated.model)
        return WikiGenerationResult(run_id, "succeeded")
    except (GenerationError, WikiGenerationError) as exc:
        error = str(exc)
    except Exception as exc:
        logger.exception("wiki page generation failed", extra={"generation_run_id": str(run_id) if run_id else None, "failure_stage": failure_stage})
        error = f"{failure_stage} failed: {type(exc).__name__}"
    if run_id is not None:
        try:
            store.add_artifact(run_id, "validation_error", error)
            store.fail(run_id, error, failure_stage)
        except Exception:
            # A database outage cannot be masked as a successful publication.
            pass
    return WikiGenerationResult(run_id or uuid4(), "failed", error)
