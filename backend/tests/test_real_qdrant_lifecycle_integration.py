"""End-to-end lifecycle proof using real PostgreSQL and Qdrant services."""

import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings
from hydrawiki.embeddings import EmbeddingResult
from hydrawiki.generation import GenerationResult
from hydrawiki.persistence import Database


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
QDRANT_URL = os.getenv("HYDRAWIKI_TEST_QDRANT_URL")
pytestmark = pytest.mark.skipif(not (DATABASE_URL and QDRANT_URL), reason="set HYDRAWIKI_TEST_DATABASE_URL and HYDRAWIKI_TEST_QDRANT_URL for real lifecycle integration")


def test_add_progress_cited_page_delete_removes_real_vectors_and_metadata(tmp_path: Path, monkeypatch) -> None:
    assert DATABASE_URL and QDRANT_URL
    source_root = tmp_path / "repositories"
    source = source_root / "fixture"
    source.mkdir(parents=True)
    (source / "app.py").write_text("def lifecycle_fixture():\n    return 'indexed'\n")
    workspace_root = tmp_path / "workspaces"
    settings = Settings(
        database_url=DATABASE_URL,
        qdrant_url=QDRANT_URL,
        local_repositories_root=str(source_root),
        workspace_root=str(workspace_root),
        generation_url="http://fake-generation:4000/v1",
        generation_model="fixture-model",
    )

    class FakeEmbedding:
        def __init__(self, *_args):
            pass

        def embed(self, _text):
            return EmbeddingResult([0.1, 0.2], "fixture-embedding")

    class FakeGenerator:
        def __init__(self, *_args):
            pass

        def generate(self, _prompt):
            return GenerationResult('{"content":"# Lifecycle","citations":[{"path":"app.py","line_start":1,"line_end":2}]}', "fixture-generation")

    monkeypatch.setattr("hydrawiki.indexing.OllamaEmbeddingAdapter", FakeEmbedding)
    monkeypatch.setattr("hydrawiki.wiki.OpenAICompatibleGenerationAdapter", FakeGenerator)
    database = Database(DATABASE_URL)
    database.migrate()

    with TestClient(create_app(settings)) as client:
        created = client.post("/api/repositories", json={"source_type": "local", "path": "fixture", "display_name": "Lifecycle fixture"})
        assert created.status_code == 201
        repository_id = created.json()["id"]
        synced = client.post(f"/api/repositories/{repository_id}/sync")
        assert synced.status_code == 201
        assert synced.json()["status"] == "succeeded"
        assert synced.json()["phase"] == "Indexed"
        assert synced.json()["percentage"] == 100
        page = client.post(f"/api/repositories/{repository_id}/pages", json={"path": "overview", "title": "Overview"})
        assert page.status_code == 201
        assert page.json()["status"] == "succeeded"
        published = client.get(f"/api/repositories/{repository_id}/pages/overview")
        assert published.status_code == 200
        assert published.json()["citations"] == [{"path": "app.py", "line_start": 1, "line_end": 2}]

        points = httpx.post(f"{QDRANT_URL}/collections/hydrawiki/points/scroll", json={"filter": {"must": [{"key": "repository_id", "match": {"value": repository_id}}]}, "limit": 10}, timeout=30)
        points.raise_for_status()
        assert points.json()["result"]["points"]

        deleted = client.delete(f"/api/repositories/{repository_id}")
        assert deleted.status_code == 200
        assert deleted.json()["lifecycle_status"] == "deleted"

    with database.connection() as connection:
        for table, column in (("repositories", "id"), ("ingestion_runs", "repository_id"), ("manifest_runs", "repository_id"), ("chunks", "repository_id"), ("generation_runs", "repository_id"), ("wiki_pages", "repository_id"), ("wiki_page_sources", "repository_id")):
            assert connection.execute(f"SELECT count(*) AS count FROM {table} WHERE {column} = %s", (repository_id,)).fetchone()["count"] == 0
    points = httpx.post(f"{QDRANT_URL}/collections/hydrawiki/points/scroll", json={"filter": {"must": [{"key": "repository_id", "match": {"value": repository_id}}]}, "limit": 10}, timeout=30)
    points.raise_for_status()
    assert points.json()["result"]["points"] == []
