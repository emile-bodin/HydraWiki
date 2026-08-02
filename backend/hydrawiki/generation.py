"""OpenAI-compatible generation adapter with normalized failures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from urllib.parse import urlsplit

import httpx


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    content: str
    model: str


def _endpoint_style(endpoint_url: str) -> str:
    path = urlsplit(endpoint_url).path.rstrip("/")
    if path.endswith("/chat/completions"):
        return "chat_completions"
    if path.endswith("/responses"):
        return "responses"
    raise GenerationError(
        "generation URL must be a full endpoint ending in /chat/completions or /responses"
    )


def _sanitize_provider_message(message: object) -> str | None:
    if not isinstance(message, str):
        return None
    compact = " ".join(message.split())
    if not compact:
        return None
    compact = re.sub(r"(?i)(authorization\s*[:=]\s*)((?!bearer\b)[^\s,;]+)", r"\1[redacted]", compact)
    compact = re.sub(r"(?i)(bearer\s+)([^\s,;]+)", r"\1[redacted]", compact)
    compact = re.sub(r"(?i)(api[ _-]?key\s*[:=]\s*)([^\s,;]+)", r"\1[redacted]", compact)
    return compact[:500]


def _provider_error_message(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    candidates = (
        error.get("message") if isinstance(error, dict) else error,
        body.get("message"),
        body.get("detail"),
    )
    for candidate in candidates:
        sanitized = _sanitize_provider_message(candidate)
        if sanitized:
            return sanitized
    return None


def _nonempty_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _responses_content(body: dict) -> str | None:
    direct = _nonempty_text(body.get("output_text"))
    if direct:
        return direct
    output = body.get("output")
    if not isinstance(output, list):
        return None
    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = _nonempty_text(part.get("text")) or _nonempty_text(part.get("content"))
                    if text:
                        text_parts.append(text)
    return "".join(text_parts) or None


def _sse_provider_error(event: dict) -> str | None:
    error = event.get("error")
    response = event.get("response")
    response_error = response.get("error") if isinstance(response, dict) else None
    candidates = (
        error.get("message") if isinstance(error, dict) else error,
        response_error.get("message") if isinstance(response_error, dict) else response_error,
        event.get("message"),
        event.get("detail"),
    )
    for candidate in candidates:
        sanitized = _sanitize_provider_message(candidate)
        if sanitized:
            return sanitized
    return None


def _responses_sse_content(body: str) -> tuple[str | None, str | None]:
    delta_parts: list[str] = []
    done_content: str | None = None
    completed_content: str | None = None
    provider_model: str | None = None
    for line in body.splitlines():
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except (JSONDecodeError, TypeError) as exc:
            raise GenerationError("generation service returned a malformed response") from exc
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type in {"error", "response.error", "response.failed"} or (
            isinstance(event_type, str) and event_type.endswith(".error")
        ):
            detail = _sse_provider_error(event)
            suffix = f": {detail}" if detail else ""
            raise GenerationError(f"generation provider returned an error{suffix}")
        if event_type == "response.output_text.delta":
            delta = _nonempty_text(event.get("delta"))
            if delta:
                delta_parts.append(delta)
        elif event_type == "response.output_text.done":
            done_content = _nonempty_text(event.get("text")) or _nonempty_text(event.get("output_text"))
        elif event_type == "response.completed":
            completed_response = event.get("response")
            if isinstance(completed_response, dict):
                provider_model = _nonempty_text(completed_response.get("model"))
                completed_content = _responses_content(completed_response)
            else:
                completed_content = _responses_content(event)
    if delta_parts:
        return "".join(delta_parts), provider_model
    return done_content or completed_content, provider_model


class OpenAICompatibleGenerationAdapter:
    """Call a configured OpenAI-compatible full generation endpoint."""

    def __init__(self, endpoint_url: str, model: str, api_key: str | None, timeout_seconds: float = 60, max_output_tokens: int = 8000):
        self.endpoint_url = endpoint_url
        self.endpoint_style = _endpoint_style(endpoint_url)
        self.model = model
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_output_tokens = max_output_tokens

    def generate(self, prompt: str) -> GenerationResult:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if self.endpoint_style == "chat_completions":
            request_body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": self.max_output_tokens}
        else:
            request_body = {"model": self.model, "input": [{"role": "user", "content": prompt}], "max_output_tokens": self.max_output_tokens}
        try:
            response = httpx.post(self.endpoint_url, headers=headers, json=request_body, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise GenerationError(f"generation service timed out for {self.endpoint_style} endpoint") from exc
        except httpx.HTTPError as exc:
            raise GenerationError("generation service unavailable") from exc
        if response.status_code >= 400:
            detail = _provider_error_message(response)
            suffix = f": {detail}" if detail else ""
            raise GenerationError(f"generation service returned HTTP {response.status_code}{suffix}")
        try:
            content: str | None
            provider_model: str | None = None
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if self.endpoint_style == "responses" and content_type == "text/event-stream":
                content, provider_model = _responses_sse_content(response.text)
            else:
                body = response.json()
                if not isinstance(body, dict):
                    raise TypeError
                if self.endpoint_style == "chat_completions":
                    content = body["choices"][0]["message"]["content"]
                else:
                    content = _responses_content(body)
                provider_model = _nonempty_text(body.get("model"))
            if not _nonempty_text(content):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GenerationError("generation service returned a malformed response") from exc
        return GenerationResult(content=content, model=provider_model or self.model)
