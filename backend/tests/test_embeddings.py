import httpx
import pytest

from hydrawiki.embeddings import EmbeddingError, OllamaEmbeddingAdapter


def response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://ollama/api/embeddings"))


def test_ollama_adapter_success_and_normalized_failures(monkeypatch) -> None:
    adapter = OllamaEmbeddingAdapter("http://ollama:11434", "test-model", 1)
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(200, {"embedding": [1, 2.5]}))
    assert adapter.embed("text").vector == [1.0, 2.5]

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(200, {}))
    with pytest.raises(EmbeddingError, match="malformed"):
        adapter.embed("text")
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(503, {}))
    with pytest.raises(EmbeddingError, match="HTTP 503"):
        adapter.embed("text")
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("late")))
    with pytest.raises(EmbeddingError, match="timed out"):
        adapter.embed("text")
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("down")))
    with pytest.raises(EmbeddingError, match="unavailable"):
        adapter.embed("text")
