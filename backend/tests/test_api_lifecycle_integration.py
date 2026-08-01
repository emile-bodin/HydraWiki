import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings
from hydrawiki.persistence import Database


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


def test_registration_survives_new_app_and_delete_removes_workspace(tmp_path: Path, monkeypatch) -> None:
    assert DATABASE_URL
    local_root = tmp_path / "repositories"
    (local_root / "repo").mkdir(parents=True)
    workspace_root = tmp_path / "workspaces"
    settings = Settings(
        database_url=DATABASE_URL,
        qdrant_url="http://qdrant:6333",
        local_repositories_root=str(local_root),
        workspace_root=str(workspace_root),
    )
    deleted_vectors = []
    class FakeVectors:
        def __init__(self, *_args): pass
        def delete(self, vector_ids): deleted_vectors.extend(vector_ids)
    monkeypatch.setattr("hydrawiki.api.QdrantVectorStore", FakeVectors)
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/repositories", json={"source_type": "local", "path": "repo", "display_name": "Repo"})
        assert created.status_code == 201
        repository_id = created.json()["id"]
    with Database(DATABASE_URL).connection() as connection:
        connection.execute("INSERT INTO index_versions (index_version, embedding_model, vector_dimension) VALUES ('delete-index', 'fake', 2) ON CONFLICT DO NOTHING")
        connection.execute("INSERT INTO chunks (id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id) VALUES (%s, %s, 'a.py', 'hash', 0, 'x', 'chunk', 1, 1, 'line-v1', 'fake', 'delete-index', 'delete-vector')", (uuid4(), repository_id))
    managed_workspace = workspace_root / repository_id
    managed_workspace.mkdir(parents=True)
    (managed_workspace / "cache").write_text("workspace data")

    with TestClient(create_app(settings)) as restarted_client:
        assert restarted_client.get("/api/repositories").json()[0]["id"] == repository_id
        deleted = restarted_client.delete(f"/api/repositories/{repository_id}")
        assert deleted.status_code == 200
        assert deleted.json()["lifecycle_status"] == "deleted"
        assert not managed_workspace.exists()
        repeated_delete = restarted_client.delete(f"/api/repositories/{repository_id}")
        assert repeated_delete.status_code == 200
        assert repeated_delete.json()["lifecycle_status"] == "deleted"
        assert deleted_vectors == ["delete-vector"]

        failed_created = restarted_client.post("/api/repositories", json={"source_type": "local", "path": "repo", "display_name": "Retry"})
        failed_id = failed_created.json()["id"]
        failed_workspace = workspace_root / failed_id
        failed_workspace.parent.mkdir(parents=True, exist_ok=True)
        failed_workspace.write_text("not a directory")
        failed_delete = restarted_client.delete(f"/api/repositories/{failed_id}")
        assert failed_delete.status_code == 500
        assert failed_delete.json()["lifecycle_status"] == "delete_failed"
        failed_workspace.unlink()
        assert restarted_client.delete(f"/api/repositories/{failed_id}").json()["lifecycle_status"] == "deleted"
