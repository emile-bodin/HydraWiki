import httpx

from hydrawiki.vectors import QdrantVectorStore


def test_qdrant_payload_contains_repository_and_chunk_ids(monkeypatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, request=httpx.Request(method, url))

    monkeypatch.setattr("httpx.request", fake_request)
    QdrantVectorStore("http://qdrant:6333").upsert([{"id": "v1", "vector": [0.1], "payload": {"repository_id": "r1", "chunk_id": "c1"}}])
    assert calls[0][2]["json"]["points"][0]["payload"] == {"repository_id": "r1", "chunk_id": "c1"}


def test_qdrant_staged_vectors_can_be_promoted_with_an_explicit_state(monkeypatch) -> None:
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, request=httpx.Request(method, url))

    monkeypatch.setattr("httpx.request", fake_request)
    QdrantVectorStore("http://qdrant:6333").set_payload(["v1"], {"hydrawiki_state": "active"})
    assert calls[0][0:2] == ("POST", "http://qdrant:6333/collections/hydrawiki/points/payload")
    assert calls[0][2]["json"] == {"points": ["v1"], "payload": {"hydrawiki_state": "active"}, "wait": True}
