"""PostgreSQL lifecycle coverage for cited wiki publication."""

import os
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hydrawiki.api import create_app
from hydrawiki.config import Settings
from hydrawiki.generation import GenerationError, GenerationResult
from hydrawiki.mermaid import MermaidError, RenderedDiagram
from hydrawiki.persistence import Database, RepositoryStore
from hydrawiki.wiki import GenerationBusyError, WikiStore, generate_wiki_page


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
    settings = Settings(
        database_url=DATABASE_URL,
        qdrant_url="http://qdrant:6333",
        generation_url="http://fake-litellm:4000/v1/chat/completions",
        generation_model="fake-model",
    )
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
        run = connection.execute("SELECT status, source_selection, configured_model, provider_model, failure_stage FROM generation_runs WHERE id = %s", (result.run_id,)).fetchone()
    assert [artifact["artifact_type"] for artifact in artifacts] == ["prompt", "response"]
    assert run["status"] == "succeeded"
    assert run["source_selection"][0]["path"] == "app.py"
    assert run["configured_model"] == "fake-model"
    assert run["provider_model"] == "fake-provider-model"
    assert run["failure_stage"] is None


def test_source_derived_generation_publishes_variable_pages_and_empty_groups(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    FakeGenerator.response = '{"structure":[{"key":"get-started","title":"Get started","pages":[]},{"key":"concepts","title":"Concepts","pages":[{"path":"concepts/service","title":"Service"}]},{"key":"guides","title":"Guides","pages":[]},{"key":"reference","title":"Reference","pages":[]},{"key":"workflows","title":"Workflows","pages":[]}],"pages":[{"group":"concepts","path":"concepts/service","title":"Service","content":"# Service","citations":[{"path":"app.py","line_start":1,"line_end":3}]}]}'

    result = generate_wiki_page(database, settings, repository["id"], "ignored", "Ignored")

    assert result.status == "succeeded"
    assert [page["path"] for page in WikiStore(database).list_pages(repository["id"])] == ["concepts/service"]
    run = WikiStore(database).get_run(result.run_id)
    assert [group["key"] for group in run["wiki_structure"]] == ["get-started", "concepts", "guides", "reference", "workflows"]


def test_duplicate_citations_are_deduplicated_before_publication(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    FakeGenerator.response = '{"content":"# Overview","citations":[{"path":"app.py","line_start":1,"line_end":3},{"path":"app.py","line_start":1,"line_end":3}]}'

    result = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")

    assert result.status == "succeeded"
    assert WikiStore(database).get_page(repository["id"], "overview")["citations"] == [{"path": "app.py", "line_start": 1, "line_end": 3}]


def test_generation_uses_responses_endpoint_without_bypassing_citation_validation(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    settings.generation_url = "http://fake-litellm:4000/v1/responses"
    captured = {}

    class ResponsesGenerator(FakeGenerator):
        def __init__(self, endpoint_url, *_args, **_kwargs):
            captured["endpoint_url"] = endpoint_url

    monkeypatch.setattr("hydrawiki.wiki.OpenAICompatibleGenerationAdapter", ResponsesGenerator)
    result = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert result.status == "succeeded"
    assert captured["endpoint_url"] == "http://fake-litellm:4000/v1/responses"
    assert WikiStore(database).get_page(repository["id"], "overview")["citations"] == [{"path": "app.py", "line_start": 1, "line_end": 3}]


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


def test_operator_read_views_expose_durable_runs_and_indexed_sources_only(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    with database.connection() as connection:
        manifest_run_id = uuid4()
        connection.execute(
            """INSERT INTO manifest_runs
            (id, repository_id, status, parser_version, phase, current_count, total_count, percentage, completed_at)
            VALUES (%s, %s, 'succeeded', 'text-v1', 'Indexed', 2, 2, 100, now())""",
            (manifest_run_id, repository["id"]),
        )
    with TestClient(create_app(settings)) as client:
        overview = client.get("/api/repositories")
        assert overview.status_code == 200
        assert overview.json()[0]["last_successful_processing_at"] is not None
        assert overview.json()[0]["current_error"] is None

        ingestion = client.get(f"/api/repositories/{repository['id']}/ingestion-runs")
        assert ingestion.status_code == 200
        assert ingestion.json()[0]["phase"] == "Indexed"
        assert ingestion.json()[0]["current_count"] == 2
        assert ingestion.json()[0]["total_count"] == 2
        assert ingestion.json()[0]["percentage"] == 100

        FakeGenerator.error = GenerationError("provider unavailable")
        failed = client.post(f"/api/repositories/{repository['id']}/pages", json={"path": "failed", "title": "Failed"})
        assert failed.status_code == 201
        assert failed.json()["status"] == "failed"
        generations = client.get(f"/api/repositories/{repository['id']}/generation-runs")
        assert generations.json()[0]["status"] == "failed"
        assert client.get(f"/api/repositories/{repository['id']}/pages").json() == []

        source = client.get(f"/api/repositories/{repository['id']}/sources/app.py")
        assert source.status_code == 200
        assert source.json() == {"path": "app.py", "content": "first\\nsecond\\nthird\\n", "line_count": 3}
        assert client.get(f"/api/repositories/{repository['id']}/sources/../../etc/passwd").status_code == 404


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


def test_generation_limit_rejects_extra_work_without_creating_a_run(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_generate(_self, _prompt):
        started.set()
        assert release.wait(5)
        return GenerationResult(FakeGenerator.response, "fake-provider-model")

    monkeypatch.setattr(FakeGenerator, "generate", slow_generate)
    first_result: list = []
    thread = threading.Thread(target=lambda: first_result.append(generate_wiki_page(Database(DATABASE_URL), settings, repository["id"], "first", "First")))
    thread.start()
    assert started.wait(5)
    with pytest.raises(GenerationBusyError, match="generation concurrency limit reached"):
        generate_wiki_page(Database(DATABASE_URL), settings, repository["id"], "second", "Second")
    release.set()
    thread.join(timeout=5)
    assert first_result[0].status == "succeeded"
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) AS count FROM generation_runs WHERE repository_id = %s", (repository["id"],)).fetchone()["count"] == 1


def test_generation_api_returns_the_bounded_response_when_limit_is_reached(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_generate(_self, _prompt):
        started.set()
        assert release.wait(5)
        return GenerationResult(FakeGenerator.response, "fake-provider-model")

    monkeypatch.setattr(FakeGenerator, "generate", slow_generate)
    first_result: list = []
    thread = threading.Thread(target=lambda: first_result.append(generate_wiki_page(Database(DATABASE_URL), settings, repository["id"], "first", "First")))
    thread.start()
    assert started.wait(5)
    with TestClient(create_app(settings)) as client:
        response = client.post(f"/api/repositories/{repository['id']}/pages", json={"path": "second", "title": "Second"})
    assert response.status_code == 409
    assert response.json()["detail"] == "generation concurrency limit reached"
    release.set()
    thread.join(timeout=5)
    assert first_result[0].status == "succeeded"


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
    failed_run = WikiStore(database).get_run(failed.run_id)
    assert failed_run["error"] == "publication failed: RuntimeError"
    assert failed_run["failure_stage"] == "publication"


def test_mermaid_failure_is_durable_and_preserves_prior_publication(monkeypatch):
    database, repository, settings = setup_indexed_repository(monkeypatch)
    FakeGenerator.response = '{"content":"# Overview\\n```mermaid\\nflowchart LR\\nHostRepos[\\"/repositories (read-only)\\"] --> Api[\\"API service :8000\\"]\\n```","citations":[{"path":"app.py","line_start":1,"line_end":3}]}'

    class SafeRenderer:
        def __init__(self, *_args): pass
        def render(self, source): return RenderedDiagram(source, '<svg xmlns="http://www.w3.org/2000/svg" style="max-width: 86.6562px; background-color: white;"><text x="1" y="2">safe</text></svg>')

    monkeypatch.setattr("hydrawiki.wiki.MermaidRenderer", SafeRenderer)
    first = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert first.status == "succeeded"
    assert WikiStore(database).get_page(repository["id"], "overview")["diagrams"][0]["status"] == "safe"

    class FailingRenderer:
        def __init__(self, *_args): pass
        def render(self, _source): raise MermaidError("Mermaid source failed server-side validation")

    monkeypatch.setattr("hydrawiki.wiki.MermaidRenderer", FailingRenderer)
    failed = generate_wiki_page(database, settings, repository["id"], "overview", "Overview")
    assert failed.status == "failed"
    assert WikiStore(database).get_page(repository["id"], "overview")["generation_run_id"] == first.run_id
    run = WikiStore(database).get_run(failed.run_id)
    assert run["failure_stage"] == "mermaid_validation"
    assert run["diagrams"] == [{"ordinal": 0, "source": 'flowchart LR\nHostRepos["/repositories (read-only)"] --> Api["API service :8000"]', "status": "failed", "svg": None, "error": "Mermaid source failed server-side validation"}]
