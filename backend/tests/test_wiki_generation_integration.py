"""PostgreSQL lifecycle coverage for cited wiki publication."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings
from hydrawiki.generation import GenerationError, GenerationResult
from hydrawiki.persistence import Database, RepositoryStore
from hydrawiki.wiki import WikiStore, generate_wiki_page


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


class FakeGenerator:
    response = '{"content":"# Overview\\nThe service starts here.","citations":[{"path":"app.py","line_start":1,"line_end":3}]}'
    error = None

    def __init__(self, *_args, **_kwargs):
        pass

    def generate(self, _prompt):
        if self.error:
            raise self.error
        return GenerationResult(self.response, "fake-provider-model")


def setup_indexed_repository(monkeypatch):
    assert DATABASE_URL
    monkeypatch.setattr("hydrawiki.wiki.OpenAICompatibleGenerationAdapter", FakeGenerator)
    FakeGenerator.error = None
    FakeGenerator.response = '{"content":"# Overview\\nThe service starts here.","citations":[{"path":"app.py","line_start":1,"line_end":3}]}'
    database = Database(DATABASE_URL)
    repository = RepositoryStore(database).create({"id": uuid4(), "source_type": "local", "source_value": "repo", "selected_ref": None, "display_name": "Wiki"})
    cache_id, manifest_run_id, chunk_id = uuid4(), uuid4(), uuid4()
    with database.connection() as connection:
        connection.execute("INSERT INTO manifest_runs (id, repository_id, status, parser_version, completed_at) VALUES (%s, %s, 'succeeded', 'text-v1', now())", (manifest_run_id, repository["id"]))
        content_hash = str(cache_id)
        connection.execute("INSERT INTO content_cache (id, content_sha256, parser_version, normalized_content, byte_size, line_count) VALUES (%s, %s, 'text-v1', 'first\\nsecond\\nthird\\n', 19, 3)", (cache_id, content_hash))
        connection.execute("INSERT INTO source_files (repository_id, path, content_sha256, byte_size, content_cache_id, parser_version, last_manifest_run_id) VALUES (%s, 'app.py', %s, 19, %s, 'text-v1', %s)", (repository["id"], content_hash, cache_id, manifest_run_id))
        connection.execute("INSERT INTO index_versions (index_version, embedding_model, vector_dimension) VALUES ('test-index', 'test-model', 2) ON CONFLICT DO NOTHING")
        connection.execute("""INSERT INTO chunks (id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id)
        VALUES (%s, %s, 'app.py', %s, 0, 'first\\nsecond\\nthird\\n', 'chunk', 1, 3, 'line-v1', 'test-model', 'test-index', %s)""", (chunk_id, repository["id"], content_hash, str(uuid4())))
    settings = Settings(database_url=DATABASE_URL, qdrant_url="http://qdrant:6333", generation_url="http://fake-litellm:4000/v1", generation_model="fake-model")
    return database, repository, settings


def test_successful_generation_persists_page_artifacts_and_citations(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    result = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert result.status == "succeeded"
    page = WikiStore(database).get_page(repository["id"], "overview")
    assert page["content"].startswith("# Overview")
    assert page["citations"] == [{"path": "app.py", "line_start": 1, "line_end": 3}]
    with database.connection() as connection:
        artifacts = list(connection.execute("SELECT artifact_type FROM generation_artifacts WHERE generation_run_id = %s ORDER BY artifact_type", (result.run_id,)))
        run = connection.execute("SELECT status, source_selection, configured_model, provider_model FROM generation_runs WHERE id = %s", (result.run_id,)).fetchone()
    assert [artifact["artifact_type"] for artifact in artifacts] == ["prompt", "response"]
    assert run["status"] == "succeeded"
    assert run["source_selection"][0]["path"] == "app.py"
    assert run["configured_model"] == "fake-model"
    assert run["provider_model"] == "fake-provider-model"


def test_generation_api_exposes_only_published_cited_pages(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    with TestClient(create_app(settings)) as client:
        generated = client.post(f"/api/repositories/{repository['id']}/pages", json={"path": "overview", "title": "Overview"})
        assert generated.status_code == 201
        assert generated.json()["status"] == "succeeded"
        pages = client.get(f"/api/repositories/{repository['id']}/pages")
        assert pages.json() == [{"path": "overview", "title": "Overview", "lifecycle_status": "published", "generation_run_id": generated.json()["id"]}]
        page = client.get(f"/api/repositories/{repository['id']}/pages/overview")
        assert page.status_code == 200
        assert page.json()["citations"] == [{"path": "app.py", "line_start": 1, "line_end": 3}]


@pytest.mark.parametrize("response", [
    '{"content":"text","citations":[]}',
    '{"content":"text","citations":[{"path":"missing.py","line_start":1,"line_end":1}]}',
    '{"content":"text","citations":[{"path":"app.py","line_start":1,"line_end":4}]}',
])
def test_missing_or_invalid_citations_fail_without_publishing(monkeypatch, response):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    FakeGenerator.response = response
    result = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert result.status == "failed"
    assert WikiStore(database).get_page(repository["id"], "overview") is None
    run = WikiStore(database).get_run(result.run_id)
    assert run["status"] == "failed"
    assert "citation" in run["error"] or "valid cited page" in run["error"]


def test_generator_failure_is_durable_and_does_not_publish(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    FakeGenerator.error = GenerationError("generation service unavailable")
    result = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert result.status == "failed"
    assert WikiStore(database).get_page(repository["id"], "overview") is None
    assert WikiStore(database).get_run(result.run_id)["error"] == "generation service unavailable"


def test_persistence_failure_preserves_existing_published_page(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    first = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert first.status == "succeeded"
    old_page = WikiStore(database).get_page(repository["id"], "overview")
    FakeGenerator.response = '{"content":"# Replacement","citations":[{"path":"app.py","line_start":1,"line_end":3}]}'

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("controlled database publication failure")

    monkeypatch.setattr(WikiStore, "publish", fail_publish)
    failed = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert failed.status == "failed"
    preserved = WikiStore(database).get_page(repository["id"], "overview")
    assert preserved["content"] == old_page["content"]
    assert WikiStore(database).get_run(failed.run_id)["error"] == "wiki page persistence failed"
