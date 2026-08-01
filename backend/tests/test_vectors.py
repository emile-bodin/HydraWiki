import httpx
import pytest

from hydrawiki.vectors import QdrantVectorStore


def test_qdrant_mutations_wait_for_operation_completion(monkeypatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        # Qdrant returns an accepted operation without wait=true. The test
        # double treats that as incomplete so callers cannot mistake request
        # acceptance for a completed mutation.
        if method != "GET":
            assert kwargs.get("params") == {"wait": "true"}
            assert "wait" not in kwargs.get("json", {})
        calls.append((method, url, kwargs))
        return httpx.Response(200, request=httpx.Request(method, url))

    monkeypatch.setattr("httpx.request", fake_request)
    store = QdrantVectorStore("http://qdrant:6333")
    point = {"id": "v1", "vector": [0.1], "payload": {"repository_id": "r1", "chunk_id": "c1"}}
    store.ensure_collection(1)
    store.upsert([point])
    store.set_payload(["v1"], {"hydrawiki_state": "active"})
    store.delete(["v1"])

    assert calls[0][2]["json"] == {"vectors": {"size": 1, "distance": "Cosine"}}
    assert calls[1][2]["json"]["points"][0]["payload"] == point["payload"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda store: store.ensure_collection(1),
        lambda store: store.upsert([]),
        lambda store: store.set_payload(["v1"], {"hydrawiki_state": "active"}),
        lambda store: store.delete(["v1"]),
    ],
)
def test_each_mutating_qdrant_request_has_wait_query_parameter(monkeypatch, mutation) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, request=httpx.Request(method, url))

    monkeypatch.setattr("httpx.request", fake_request)
    mutation(QdrantVectorStore("http://qdrant:6333"))
    assert calls[0][2]["params"] == {"wait": "true"}
