"""OpenAI-compatible generation adapter with normalized failures."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    content: str
    model: str


class OpenAICompatibleGenerationAdapter:
    """Call a configured LiteLLM/OpenAI-compatible chat-completions endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout_seconds: float = 60, max_output_tokens: int = 8000):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_output_tokens = max_output_tokens

    def generate(self, prompt: str) -> GenerationResult:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": self.max_output_tokens},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise GenerationError("generation service timed out") from exc
        except httpx.HTTPError as exc:
            raise GenerationError("generation service unavailable") from exc
        if response.status_code >= 400:
            raise GenerationError(f"generation service returned HTTP {response.status_code}")
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GenerationError("generation service returned a malformed response") from exc
        return GenerationResult(content=content, model=str(body.get("model") or self.model))
