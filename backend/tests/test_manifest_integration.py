"""PostgreSQL-backed manifest lifecycle tests; run with HYDRAWIKI_TEST_DATABASE_URL."""

import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from hydrawiki.config import Settings
from hydrawiki.manifest import ManifestBusyError, ManifestStore, run_manifest
from hydrawiki.persistence import Database, RepositoryStore


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


def test_manifest_delta_is_atomic_reusable_and_survives_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL
    root = tmp_path / "repositories"
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    (repo_path / "same.py").write_text("same\n")
    (repo_path / "gone.py").write_text("gone\n")
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", local_repositories_root=str(root))
    database = Database(DATABASE_URL)
    repository_id = uuid4()
    repository = RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Fixture"})

    first = run_manifest(database, settings, repository)
    assert first.status == "succeeded"
    first_entries = ManifestStore(database).entries(first.run_id)
    assert {entry["classification"] for entry in first_entries} == {"new"}

    (repo_path / "same.py").write_text("same\n")
    (repo_path / "gone.py").unlink()
    (repo_path / "new.py").write_text("same\n")
    second = run_manifest(Database(DATABASE_URL), settings, repository)
    assert second.classifications == {"new": 1, "changed": 0, "unchanged": 1, "missing": 1}
    entries = ManifestStore(database).entries(second.run_id)
    assert {entry["path"]: entry["classification"] for entry in entries} == {"gone.py": "missing", "new.py": "new", "same.py": "unchanged"}
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM source_files WHERE repository_id = %s", (repository_id,)).fetchone()["count"] == 2
        assert connection.execute("SELECT count(*) AS count FROM content_cache WHERE id IN (SELECT content_cache_id FROM source_files WHERE repository_id = %s)", (repository_id,)).fetchone()["count"] == 1

    before = [(row["path"], row["content_sha256"]) for row in connection_rows(database, "SELECT path, content_sha256 FROM source_files WHERE repository_id = %s ORDER BY path", repository_id)]
    (repo_path / "new.py").write_text("too large")
    failed = run_manifest(Database(DATABASE_URL), settings.model_copy(update={"max_source_file_size_bytes": 2}), repository)
    assert failed.status == "failed"
    after = [(row["path"], row["content_sha256"]) for row in connection_rows(database, "SELECT path, content_sha256 FROM source_files WHERE repository_id = %s ORDER BY path", repository_id)]
    assert after == before

    monkeypatch.setattr("hydrawiki.manifest.PARSER_VERSION", "text-v2")
    versioned = run_manifest(Database(DATABASE_URL), settings, repository)
    assert versioned.classifications["changed"] == 2
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM content_cache WHERE parser_version = 'text-v2'").fetchone()["count"] == 2


def connection_rows(database: Database, query: str, repository_id):
    with database.connection() as connection:
        return list(connection.execute(query, (repository_id,)))


def test_invalid_source_records_failed_run_without_inventory(tmp_path: Path) -> None:
    assert DATABASE_URL
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", local_repositories_root=str(tmp_path))
    database = Database(DATABASE_URL)
    repository_id = uuid4()
    repository = RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "does-not-exist", "selected_ref": None, "display_name": "Invalid"})
    result = run_manifest(database, settings, repository)
    assert result.status == "failed"
    assert ManifestStore(database).get(result.run_id)["status"] == "failed"
    assert connection_rows(database, "SELECT path FROM source_files WHERE repository_id = %s", repository_id) == []


def test_concurrent_manifest_runs_are_serialized_by_postgres(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL
    root = tmp_path / "repositories"
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    (repo_path / "file.py").write_text("content\n")
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", local_repositories_root=str(root))
    database = Database(DATABASE_URL)
    repository_id = uuid4()
    repository = RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Concurrent"})
    started = threading.Event()
    release = threading.Event()
    original_discovery = __import__("hydrawiki.manifest", fromlist=["discover_eligible_files"]).discover_eligible_files

    def slow_discovery(source_root, current_settings):
        started.set()
        assert release.wait(5)
        return original_discovery(source_root, current_settings)

    monkeypatch.setattr("hydrawiki.manifest.discover_eligible_files", slow_discovery)
    first_result: list = []

    def first_run() -> None:
        first_result.append(run_manifest(Database(DATABASE_URL), settings, repository))

    first_thread = threading.Thread(target=first_run)
    first_thread.start()
    assert started.wait(5)
    with pytest.raises(ManifestBusyError, match="already running"):
        run_manifest(Database(DATABASE_URL), settings, repository)
    release.set()
    first_thread.join(timeout=5)
    assert first_result[0].status == "succeeded"
    with database.connection() as connection:
        statuses = list(connection.execute("SELECT status FROM manifest_runs WHERE repository_id = %s ORDER BY started_at", (repository_id,)))
    assert [row["status"] for row in statuses] == ["succeeded"]


def test_excluded_repository_bytes_breach_preserves_previous_inventory(tmp_path: Path) -> None:
    assert DATABASE_URL
    root = tmp_path / "repositories"
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    (repo_path / "file.py").write_text("valid\n")
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", local_repositories_root=str(root), max_repository_size_bytes=100)
    database = Database(DATABASE_URL)
    repository_id = uuid4()
    repository = RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Size"})
    successful = run_manifest(database, settings, repository)
    assert successful.status == "succeeded"
    before = [(row["path"], row["content_sha256"]) for row in connection_rows(database, "SELECT path, content_sha256 FROM source_files WHERE repository_id = %s", repository_id)]
    (repo_path / ".git").mkdir()
    (repo_path / ".git" / "pack.bin").write_bytes(b"x" * 101)
    failed = run_manifest(Database(DATABASE_URL), settings, repository)
    assert failed.status == "failed"
    after = [(row["path"], row["content_sha256"]) for row in connection_rows(database, "SELECT path, content_sha256 FROM source_files WHERE repository_id = %s", repository_id)]
    assert after == before


def test_unexpected_scan_error_releases_postgres_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert DATABASE_URL
    root = tmp_path / "repositories"
    repo_path = root / "repo"
    repo_path.mkdir(parents=True)
    (repo_path / "file.py").write_text("content\n")
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", local_repositories_root=str(root))
    database = Database(DATABASE_URL)
    repository_id = uuid4()
    repository = RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Lease"})
    manifest_module = __import__("hydrawiki.manifest", fromlist=["discover_eligible_files"])
    original_discovery = manifest_module.discover_eligible_files
    monkeypatch.setattr(manifest_module, "discover_eligible_files", lambda *_: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    failed = run_manifest(database, settings, repository)
    assert failed.status == "failed"
    monkeypatch.setattr(manifest_module, "discover_eligible_files", original_discovery)
    recovered = run_manifest(Database(DATABASE_URL), settings, repository)
    assert recovered.status == "succeeded"
