"""Qdrant derived-store boundary."""

from __future__ import annotations

import httpx


class VectorStoreError(RuntimeError):
    pass


class QdrantVectorStore:
    def __init__(self, base_url: str, collection: str = "hydrawiki"):
        self.base_url = base_url.rstrip("/")
        self.collection = collection

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = httpx.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise VectorStoreError("vector service unavailable or rejected the request") from exc

    def ensure_collection(self, dimension: int) -> None:
        try:
            self._request(
                "PUT",
                f"/collections/{self.collection}",
                params={"wait": "true"},
                json={"vectors": {"size": dimension, "distance": "Cosine"}},
            )
        except VectorStoreError:
            # Existing collections are valid; dimension is checked by Qdrant on upsert.
            try:
                self._request("GET", f"/collections/{self.collection}")
            except VectorStoreError:
                raise

    def upsert(self, points: list[dict]) -> None:
        self._request(
            "PUT",
            f"/collections/{self.collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )

    def delete(self, vector_ids: list[str]) -> None:
        if vector_ids:
            self._request(
                "POST",
                f"/collections/{self.collection}/points/delete",
                params={"wait": "true"},
                json={"points": vector_ids},
            )

    def set_payload(self, vector_ids: list[str], payload: dict) -> None:
        if vector_ids:
            self._request(
                "POST",
                f"/collections/{self.collection}/points/payload",
                params={"wait": "true"},
                json={"points": vector_ids, "payload": payload},
            )
