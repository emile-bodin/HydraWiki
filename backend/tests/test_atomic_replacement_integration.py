"""Failure-injection coverage for the Phase-4 replacement protocol."""

import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from hydrawiki.config import Settings
from hydrawiki.manifest import run_manifest
from hydrawiki.persistence import Database, RepositoryStore


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


class FakeEmbedding:
    fail_prompt = None

    def __init__(self, *_args, **_kwargs):
        pass

    def embed(self, text):
        if self.fail_prompt and self.fail_prompt in text:
            raise RuntimeError("controlled embedding failure")
        return type("Result", (), {"vector": [float(len(text)), 1.0]})()


class FakeVectors:
    points = {}
    upsert_count = 0
    fail_upsert_at = None
    fail_delete_once = False
    retirement_ids = set()

    def __init__(self, *_args, **_kwargs):
        pass

    def ensure_collection(self, _dimension):
        pass

    def upsert(self, points):
        type(self).upsert_count += 1
        if self.fail_upsert_at == self.upsert_count:
            raise RuntimeError("controlled Qdrant upsert failure")
        self.points.update({point["id"]: point for point in points})

    def set_payload(self, vector_ids, payload):
        for vector_id in vector_ids:
            if vector_id in self.points:
                self.points[vector_id]["payload"].update(payload)

    def delete(self, vector_ids):
        if self.fail_delete_once and set(vector_ids) & self.retirement_ids:
            type(self).fail_delete_once = False
            raise RuntimeError("controlled Qdrant retirement failure")
        for vector_id in vector_ids:
            self.points.pop(vector_id, None)


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert DATABASE_URL
    FakeEmbedding.fail_prompt = None
    FakeVectors.points = {}
    FakeVectors.upsert_count = 0
    FakeVectors.fail_upsert_at = None
    FakeVectors.fail_delete_once = False
    FakeVectors.retirement_ids = set()
    monkeypatch.setattr("hydrawiki.indexing.OllamaEmbeddingAdapter", FakeEmbedding)
    monkeypatch.setattr("hydrawiki.indexing.QdrantVectorStore", FakeVectors)
    root = tmp_path / "repositories"
    repository_path = root / "repo"
    repository_path.mkdir(parents=True)
    (repository_path / "early.py").write_text("early\n")
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://controlled-qdrant:6333", local_repositories_root=str(root))
    database = Database(DATABASE_URL)
    repository = RepositoryStore(database).create({"id": uuid4(), "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Atomic"})
    initial = run_manifest(database, settings, repository)
    assert initial.status == "succeeded", initial.error
    return database, repository, settings, repository_path


@pytest.mark.parametrize("failure", ["embedding", "qdrant"])
def test_failed_multifile_replacement_preserves_state_and_retry_is_clean(tmp_path, monkeypatch, failure):
    database, repository, settings, repository_path = _setup(tmp_path, monkeypatch)
    with database.connection() as connection:
        before_source = list(connection.execute("SELECT path, content_sha256 FROM source_files WHERE repository_id = %s ORDER BY path", (repository["id"],)))
        before_chunks = list(connection.execute("SELECT path, vector_id FROM chunks WHERE repository_id = %s ORDER BY path", (repository["id"],)))
    old_vectors = set(FakeVectors.points)
    (repository_path / "early.py").write_text("early changed\n")
    (repository_path / "later.py").write_text("later\n")
    if failure == "embedding":
        FakeEmbedding.fail_prompt = "later"
    else:
        FakeVectors.fail_upsert_at = FakeVectors.upsert_count + 2
    failed = run_manifest(Database(DATABASE_URL), settings, repository)
    assert failed.status == "failed"
    if failure == "embedding":
        recorded = connection_rows(database, "SELECT error FROM manifest_runs WHERE id = %s", failed.run_id)[0]["error"]
        assert "embedding failed for path=later.py" in recorded
        assert "chunk=0" in recorded
        assert "input_characters=" in recorded
    with database.connection() as connection:
        assert list(connection.execute("SELECT path, content_sha256 FROM source_files WHERE repository_id = %s ORDER BY path", (repository["id"],))) == before_source
        assert list(connection.execute("SELECT path, vector_id FROM chunks WHERE repository_id = %s ORDER BY path", (repository["id"],))) == before_chunks
        assert connection.execute("SELECT count(*) AS count FROM staged_chunks").fetchone()["count"] == 0
    assert set(FakeVectors.points) == old_vectors
    FakeEmbedding.fail_prompt = None
    FakeVectors.fail_upsert_at = None
    retried = run_manifest(Database(DATABASE_URL), settings, repository)
    assert retried.status == "succeeded"
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM staged_chunks").fetchone()["count"] == 0
        assert connection.execute("SELECT count(*) AS count FROM chunks WHERE repository_id = %s", (repository["id"],)).fetchone()["count"] == 2


def test_postgresql_promotion_failure_cleans_staged_vectors_and_preserves_state(tmp_path, monkeypatch):
    database, repository, settings, repository_path = _setup(tmp_path, monkeypatch)
    with database.connection() as connection:
        before = list(connection.execute("SELECT path, content_sha256 FROM source_files WHERE repository_id = %s", (repository["id"],)))
    (repository_path / "early.py").write_text("changed\n")
    original = Database.connection
    failed = {"value": False}

    class FaultConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, *args, **kwargs):
            if not failed["value"] and "INSERT INTO chunks" in query:
                failed["value"] = True
                raise RuntimeError("controlled PostgreSQL promotion failure")
            return self.connection.execute(query, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    class FaultDatabase(Database):
        @contextmanager
        def connection(self):
            with original(self) as connection:
                yield FaultConnection(connection)

    result = run_manifest(FaultDatabase(DATABASE_URL), settings, repository)
    assert result.status == "failed"
    with database.connection() as connection:
        assert list(connection.execute("SELECT path, content_sha256 FROM source_files WHERE repository_id = %s", (repository["id"],))) == before
        assert connection.execute("SELECT count(*) AS count FROM staged_chunks").fetchone()["count"] == 0
    assert all(point["payload"]["hydrawiki_state"] == "active" for point in FakeVectors.points.values())


def test_retirement_failure_is_recoverable_without_losing_old_vectors(tmp_path, monkeypatch):
    database, repository, settings, repository_path = _setup(tmp_path, monkeypatch)
    old_vectors = set(FakeVectors.points)
    (repository_path / "early.py").write_text("changed\n")
    FakeVectors.fail_delete_once = True
    FakeVectors.retirement_ids = old_vectors
    failed = run_manifest(Database(DATABASE_URL), settings, repository)
    assert failed.status == "failed"
    assert old_vectors <= set(FakeVectors.points)
    recovered = run_manifest(Database(DATABASE_URL), settings, repository)
    assert recovered.status == "succeeded"
    assert not old_vectors & set(FakeVectors.points)
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM staged_chunks").fetchone()["count"] == 0
        assert connection.execute("SELECT count(*) AS count FROM index_replacements WHERE status = 'recoverable'").fetchone()["count"] == 0
    repository_path.joinpath("early.py").unlink()
    missing = run_manifest(Database(DATABASE_URL), settings, repository)
    assert missing.status == "succeeded"
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM chunks WHERE repository_id = %s", (repository["id"],)).fetchone()["count"] == 0
