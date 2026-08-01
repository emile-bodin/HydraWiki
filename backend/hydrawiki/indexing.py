"""Phase-4 chunk, embed and vector replacement workflow."""

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


def index_manifest(database: Database, settings: Settings, repository_id: UUID, run_id: UUID) -> None:
    database.migrate()
    adapter = OllamaEmbeddingAdapter(str(settings.ollama_url), settings.embedding_model, settings.embedding_timeout_seconds)
    vectors = QdrantVectorStore(str(settings.qdrant_url))
    with database.connection() as connection:
        configured = connection.execute("SELECT * FROM index_versions WHERE index_version = %s", (settings.embedding_index_version,)).fetchone()
        if configured is not None and configured["embedding_model"] != settings.embedding_model:
            raise IndexingError("embedding model changed; reindex required")
        entries = list(connection.execute("SELECT * FROM manifest_entries WHERE manifest_run_id = %s ORDER BY path", (run_id,)))
        source_hashes = {row["path"]: row["content_sha256"] for row in connection.execute("SELECT path, content_sha256 FROM source_files WHERE repository_id = %s", (repository_id,))}

        def requires_indexing(item, existing):
            return item["classification"] != "unchanged" or not existing or any(
                row["content_sha256"] != source_hashes.get(item["path"])
                or row["chunker_version"] != settings.chunker_version
                or row["embedding_model"] != settings.embedding_model
                or row["index_version"] != settings.embedding_index_version
                for row in existing
            )

        existing_by_path = {
            item["path"]: list(connection.execute("SELECT * FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, item["path"])))
            for item in entries
        }
        connection.execute("UPDATE manifest_runs SET phase = 'Embedding', current_count = 0, total_count = %s, percentage = 0 WHERE id = %s", (sum(requires_indexing(item, existing_by_path[item["path"]]) for item in entries), run_id))
        current = 0
        for entry in entries:
            path, kind = entry["path"], entry["classification"]
            old = existing_by_path[path]
            if not requires_indexing(entry, old):
                continue
            if kind == "missing":
                vectors.delete([row["vector_id"] for row in old])
                connection.execute("DELETE FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, path))
                connection.execute("DELETE FROM source_files WHERE repository_id = %s AND path = %s", (repository_id, path))
                current += 1
                connection.execute("UPDATE manifest_runs SET current_count = %s, percentage = CASE WHEN total_count = 0 THEN 100 ELSE (%s * 100 / total_count) END WHERE id = %s", (current, current, run_id))
                continue
            source = connection.execute("SELECT cc.normalized_content, sf.content_sha256 FROM source_files sf JOIN content_cache cc ON cc.id = sf.content_cache_id WHERE sf.repository_id = %s AND sf.path = %s", (repository_id, path)).fetchone()
            if source is None:
                raise IndexingError(f"source content unavailable for {path}")
            chunks = chunk_content(source["normalized_content"], settings.chunk_max_lines)
            if not chunks:
                vectors.delete([row["vector_id"] for row in old])
                connection.execute("DELETE FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, path))
                continue
            points, records = [], []
            for chunk in chunks:
                with embedding_slot(database, settings.embedding_max_concurrency):
                    result = adapter.embed(chunk.text)
                with database.connection() as verify:
                    version = verify.execute("SELECT * FROM index_versions WHERE index_version = %s FOR UPDATE", (settings.embedding_index_version,)).fetchone()
                    if version is None:
                        verify.execute("INSERT INTO index_versions (index_version, embedding_model, vector_dimension, verified_at) VALUES (%s, %s, %s, now())", (settings.embedding_index_version, settings.embedding_model, len(result.vector)))
                    elif version["embedding_model"] != settings.embedding_model or (version["vector_dimension"] is not None and version["vector_dimension"] != len(result.vector)):
                        raise IndexingError("embedding model or vector dimension changed; reindex required")
                    elif version["vector_dimension"] is None:
                        verify.execute("UPDATE index_versions SET vector_dimension = %s, verified_at = now() WHERE index_version = %s", (len(result.vector), settings.embedding_index_version))
                vector_id = str(uuid4())
                chunk_id = uuid4()
                records.append((chunk_id, repository_id, path, source["content_sha256"], chunk, vector_id))
                points.append({"id": vector_id, "vector": result.vector, "payload": {"repository_id": str(repository_id), "chunk_id": str(chunk_id), "path": path, "line_start": chunk.line_start, "line_end": chunk.line_end, "embedding_model": settings.embedding_model, "index_version": settings.embedding_index_version}})
            vectors.ensure_collection(len(points[0]["vector"]))
            vectors.upsert(points)
            vectors.delete([row["vector_id"] for row in old])
            connection.execute("DELETE FROM chunks WHERE repository_id = %s AND path = %s", (repository_id, path))
            for chunk_id, repo, source_path, sha, chunk, vector_id in records:
                connection.execute("INSERT INTO chunks (id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (chunk_id, repo, source_path, sha, chunk.ordinal, chunk.text, chunk.content_hash, chunk.line_start, chunk.line_end, settings.chunker_version, settings.embedding_model, settings.embedding_index_version, vector_id))
            current += 1
            connection.execute("UPDATE manifest_runs SET current_count = %s, percentage = CASE WHEN total_count = 0 THEN 100 ELSE (%s * 100 / total_count) END WHERE id = %s", (current, current, run_id))
        connection.execute("UPDATE manifest_runs SET phase = 'Indexed', current_count = total_count, percentage = 100 WHERE id = %s", (run_id,))
