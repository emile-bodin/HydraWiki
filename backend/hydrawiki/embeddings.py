"""Embeddings-only Ollama adapter with normalized, truthful failures."""

from __future__ import annotations

from dataclasses import dataclass
import httpx


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    model: str


class OllamaEmbeddingAdapter:
    def __init__(self, base_url: str, model: str, timeout_seconds: float = 30):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds)

    def embed(self, text: str) -> EmbeddingResult:
        try:
            response = httpx.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingError("embedding service timed out") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("embedding service unavailable") from exc
        if response.status_code >= 400:
            raise EmbeddingError(f"embedding service returned HTTP {response.status_code}")
        try:
            body = response.json()
            vector = body["embedding"]
            if not isinstance(vector, list) or not vector or not all(isinstance(value, (int, float)) for value in vector):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("embedding service returned a malformed response") from exc
        return EmbeddingResult([float(value) for value in vector], body.get("model", self.model))
