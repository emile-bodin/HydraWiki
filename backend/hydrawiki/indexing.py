"""Phase-4 staged chunk, embedding, and vector replacement workflow."""

from __future__ import annotations

import time
from contextlib import contextmanager
from uuid import UUID, uuid4

from .chunking import chunk_content
from .config import Settings
from .embeddings import OllamaEmbeddingAdapter
from .persistence import Database
from .vectors import QdrantVectorStore


class IndexingError(RuntimeError):
    pass


@contextmanager
def replacement_lease(database: Database, run_id: UUID):
    """Hold exclusive ownership of an index replacement while it is active."""
    with database.connection() as connection:
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(hashtext('hydrawiki.index-replacement'), hashtext(%s)) AS acquired",
            (str(run_id),),
        ).fetchone()["acquired"]
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            connection.execute(
                "SELECT pg_advisory_unlock(hashtext('hydrawiki.index-replacement'), hashtext(%s))",
                (str(run_id),),
            )


@contextmanager
def embedding_slot(database: Database, slots: int = 2, timeout: float = 30):
    """Acquire one of two PostgreSQL advisory-lock slots across all processes."""
    with database.connection() as connection:
        deadline = time.monotonic() + timeout
        acquired = False
        while time.monotonic() < deadline and not acquired:
            for slot in range(slots):
                acquired = connection.execute("SELECT pg_try_advisory_lock(hashtext('hydrawiki.embedding') + %s) AS acquired", (slot,)).fetchone()["acquired"]
                if acquired:
                    break
            if not acquired:
                time.sleep(0.02)
        if not acquired:
            raise IndexingError("embedding concurrency limit reached")
        try:
            yield
        finally:
            connection.execute("SELECT pg_advisory_unlock(hashtext('hydrawiki.embedding') + %s)", (slot,))


def _set_run_error(database: Database, run_id: UUID, status: str, error: str) -> None:
    with database.connection() as connection:
        connection.execute(
            "UPDATE index_replacements SET status = %s, error = %s, updated_at = now() WHERE run_id = %s",
            (status, error[:2000], run_id),
        )


def recover_replacements(database: Database, vectors: QdrantVectorStore) -> None:
    """Finish durable post-commit work or remove pre-commit staged vectors."""
    database.migrate()
    with database.connection() as connection:
        replacements = list(connection.execute("SELECT * FROM index_replacements WHERE status <> 'succeeded' ORDER BY created_at"))
    recovery_error = None
    for replacement in replacements:
        with replacement_lease(database, replacement["run_id"]) as acquired:
            if not acquired:
                continue
            staged = list(replacement["staged_vector_ids"] or [])
            old = list(replacement["old_vector_ids"] or [])
            try:
                if replacement["status"] in ("activating", "retiring") or replacement["promotion_complete"]:
                    vectors.set_payload(staged, {"hydrawiki_state": "active"})
                    vectors.delete(old)
                    with database.connection() as connection:
                        connection.execute("DELETE FROM staged_chunks WHERE replacement_run_id = %s", (replacement["run_id"],))
                        connection.execute("UPDATE index_replacements SET status = 'succeeded', error = NULL, updated_at = now() WHERE run_id = %s", (replacement["run_id"],))
                    continue
                vectors.delete(staged)
                with database.connection() as connection:
                    connection.execute("DELETE FROM staged_chunks WHERE replacement_run_id = %s", (replacement["run_id"],))
                    connection.execute("UPDATE index_replacements SET status = 'failed', error = NULL, updated_at = now() WHERE run_id = %s", (replacement["run_id"],))
            except Exception as exc:
                _set_run_error(database, replacement["run_id"], "recoverable", str(exc))
                recovery_error = recovery_error or exc
    if recovery_error is not None:
        raise IndexingError(f"durable replacement recovery is incomplete: {recovery_error}") from recovery_error


def _cleanup_failed(database: Database, vectors: QdrantVectorStore, run_id: UUID, error: Exception) -> None:
    with database.connection() as connection:
        row = connection.execute("SELECT staged_vector_ids FROM index_replacements WHERE run_id = %s", (run_id,)).fetchone()
    try:
        vectors.delete(list(row["staged_vector_ids"] or []) if row else [])
    except Exception as cleanup_error:
        _set_run_error(database, run_id, "recoverable", f"{error}; staged-vector cleanup failed: {cleanup_error}")
        raise IndexingError(f"{error}; recovery required for staged vectors") from error
    with database.connection() as connection:
        connection.execute("DELETE FROM staged_chunks WHERE replacement_run_id = %s", (run_id,))
    _set_run_error(database, run_id, "failed", str(error))


def index_manifest(database: Database, settings: Settings, repository_id: UUID, run_id: UUID) -> None:
    with replacement_lease(database, run_id) as acquired:
        if not acquired:
            raise IndexingError("index replacement is already active")
        _index_manifest(database, settings, repository_id, run_id)


def _index_manifest(database: Database, settings: Settings, repository_id: UUID, run_id: UUID) -> None:
    database.migrate()
    adapter = OllamaEmbeddingAdapter(str(settings.ollama_url), settings.embedding_model, settings.embedding_timeout_seconds)
    vectors = QdrantVectorStore(str(settings.qdrant_url))
    recover_replacements(database, vectors)

    with database.connection() as connection:
        configured = connection.execute("SELECT * FROM index_versions WHERE index_version = %s", (settings.embedding_index_version,)).fetchone()
        if configured is not None and configured["embedding_model"] != settings.embedding_model:
            raise IndexingError("embedding model changed; reindex required")
        entries = list(connection.execute("SELECT * FROM manifest_entries WHERE manifest_run_id = %s ORDER BY path", (run_id,)))
        old_chunks = {entry["path"]: list(connection.execute("SELECT * FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, entry["path"]))) for entry in entries}

        def requires_indexing(entry: dict, existing: list[dict]) -> bool:
            return entry["classification"] != "unchanged" or not existing or any(
                row["content_sha256"] != entry["content_sha256"]
                or row["chunker_version"] != settings.chunker_version
                or row["embedding_model"] != settings.embedding_model
                or row["index_version"] != settings.embedding_index_version
                for row in existing
            )

        affected = [entry for entry in entries if requires_indexing(entry, old_chunks[entry["path"]])]
        old_vector_ids = [row["vector_id"] for entry in affected for row in old_chunks[entry["path"]]]
        connection.execute("INSERT INTO index_replacements (run_id, repository_id, status, old_vector_ids) VALUES (%s, %s, 'staging', %s)", (run_id, repository_id, old_vector_ids))
        connection.execute("UPDATE manifest_runs SET phase = 'Embedding', current_count = 0, total_count = %s, percentage = 0 WHERE id = %s", (len(affected), run_id))

    staged_rows: list[tuple] = []
    dimension: int | None = configured["vector_dimension"] if configured else None
    completed = 0
    try:
        for entry in affected:
            path = entry["path"]
            if entry["classification"] == "missing":
                completed += 1
                continue
            with database.connection() as connection:
                source = connection.execute(
                    "SELECT normalized_content FROM content_cache WHERE id = %s",
                    (entry["content_cache_id"],),
                ).fetchone()
            if source is None:
                raise IndexingError(f"source content unavailable for {path}")
            chunks = chunk_content(source["normalized_content"], settings.chunk_max_lines, settings.embedding_max_input_characters)
            points = []
            for chunk in chunks:
                try:
                    with embedding_slot(database, settings.embedding_max_concurrency):
                        result = adapter.embed(chunk.text)
                except Exception as exc:
                    raise IndexingError(
                        f"embedding failed for path={path} chunk={chunk.ordinal} "
                        f"lines={chunk.line_start}-{chunk.line_end} input_characters={len(chunk.text)}: {exc}"
                    ) from exc
                if dimension is None:
                    dimension = len(result.vector)
                elif dimension != len(result.vector):
                    raise IndexingError("embedding model or vector dimension changed; reindex required")
                chunk_id, vector_id = uuid4(), str(uuid4())
                staged_rows.append((run_id, chunk_id, repository_id, path, entry["content_sha256"], chunk.ordinal, chunk.text, chunk.content_hash, chunk.line_start, chunk.line_end, settings.chunker_version, settings.embedding_model, settings.embedding_index_version, vector_id))
                points.append({"id": vector_id, "vector": result.vector, "payload": {"repository_id": str(repository_id), "chunk_id": str(chunk_id), "path": path, "line_start": chunk.line_start, "line_end": chunk.line_end, "embedding_model": settings.embedding_model, "index_version": settings.embedding_index_version, "hydrawiki_state": "staged", "replacement_id": str(run_id)}})
            if points:
                vectors.ensure_collection(len(points[0]["vector"]))
                with database.connection() as connection:
                    connection.execute("UPDATE index_replacements SET staged_vector_ids = staged_vector_ids || %s, updated_at = now() WHERE run_id = %s", ([point["id"] for point in points], run_id))
                vectors.upsert(points)
            completed += 1
            with database.connection() as connection:
                connection.execute("UPDATE manifest_runs SET current_count = %s, percentage = CASE WHEN total_count = 0 THEN 100 ELSE (%s * 100 / total_count) END WHERE id = %s", (completed, completed, run_id))

        with database.connection() as connection:
            for staged_row in staged_rows:
                connection.execute(
                    "INSERT INTO staged_chunks (replacement_run_id, id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    staged_row,
                )

        # This is the only PostgreSQL promotion transaction. Prior source/chunk
        # rows and old vectors are untouched until every staged write succeeds.
        with database.connection() as connection:
            for entry in entries:
                path = entry["path"]
                if entry["classification"] == "missing":
                    connection.execute("DELETE FROM source_files WHERE repository_id = %s AND path = %s", (repository_id, path))
                else:
                    connection.execute(
                        "INSERT INTO source_files (repository_id, path, content_sha256, byte_size, content_cache_id, parser_version, last_manifest_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (repository_id, path) DO UPDATE SET content_sha256 = EXCLUDED.content_sha256, byte_size = EXCLUDED.byte_size, content_cache_id = EXCLUDED.content_cache_id, parser_version = EXCLUDED.parser_version, last_manifest_run_id = EXCLUDED.last_manifest_run_id",
                        (repository_id, path, entry["content_sha256"], entry["byte_size"], entry["content_cache_id"], "text-v1", run_id),
                    )
            for entry in affected:
                path = entry["path"]
                connection.execute("DELETE FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, path))
            if dimension is not None:
                connection.execute(
                    "INSERT INTO index_versions (index_version, embedding_model, vector_dimension, verified_at) VALUES (%s,%s,%s,now()) ON CONFLICT (index_version) DO UPDATE SET vector_dimension = EXCLUDED.vector_dimension, verified_at = now()",
                    (settings.embedding_index_version, settings.embedding_model, dimension),
                )
            connection.execute(
                "INSERT INTO chunks (id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id) SELECT id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id FROM staged_chunks WHERE replacement_run_id = %s",
                (run_id,),
            )
            connection.execute("UPDATE index_replacements SET status = 'activating', promotion_complete = TRUE, updated_at = now() WHERE run_id = %s", (run_id,))

        with database.connection() as connection:
            replacement = connection.execute("SELECT staged_vector_ids, old_vector_ids FROM index_replacements WHERE run_id = %s", (run_id,)).fetchone()
        staged_ids = list(replacement["staged_vector_ids"] or [])
        old_ids = list(replacement["old_vector_ids"] or [])
        vectors.set_payload(staged_ids, {"hydrawiki_state": "active"})
        with database.connection() as connection:
            connection.execute("UPDATE index_replacements SET status = 'retiring', updated_at = now() WHERE run_id = %s", (run_id,))
        vectors.delete(old_ids)
        with database.connection() as connection:
            connection.execute("UPDATE index_replacements SET status = 'succeeded', error = NULL, updated_at = now() WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM staged_chunks WHERE replacement_run_id = %s", (run_id,))
            connection.execute("UPDATE manifest_runs SET status = 'succeeded', phase = 'Indexed', current_count = total_count, percentage = 100, completed_at = now(), error = NULL WHERE id = %s", (run_id,))
    except Exception as exc:
        with database.connection() as connection:
            replacement = connection.execute("SELECT status, promotion_complete FROM index_replacements WHERE run_id = %s", (run_id,)).fetchone()
        if replacement and (replacement["status"] in ("activating", "retiring") or replacement["promotion_complete"]):
            _set_run_error(database, run_id, "recoverable", str(exc))
        else:
            _cleanup_failed(database, vectors, run_id, exc)
        raise
