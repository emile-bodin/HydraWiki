import re

import httpx
import pytest

from hydrawiki.generation import GenerationError, OpenAICompatibleGenerationAdapter


def response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://litellm/v1/chat/completions"))


def test_openai_compatible_adapter_uses_configured_chat_completions_endpoint_model_and_optional_bearer_key(monkeypatch) -> None:
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured.update(kwargs)
        return response(200, {"model": "provider-model", "choices": [{"message": {"content": "generated"}}]})

    monkeypatch.setattr("httpx.post", fake_post)
    result = OpenAICompatibleGenerationAdapter("http://litellm:4000/v1/chat/completions", "configured-model", "test-key", 7, 123).generate("prompt")
    assert result.content == "generated"
    assert result.model == "provider-model"
    assert captured["url"] == "http://litellm:4000/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["json"]["model"] == "configured-model"
    assert captured["json"]["messages"] == [{"role": "user", "content": "prompt"}]
    assert captured["json"]["max_tokens"] == 123


def test_openai_compatible_adapter_uses_configured_responses_endpoint_and_parses_output(monkeypatch) -> None:
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured.update(kwargs)
        return response(200, {"model": "provider-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": "generated"}]}]})

    monkeypatch.setattr("httpx.post", fake_post)
    result = OpenAICompatibleGenerationAdapter("http://litellm:4000/v1/responses", "configured-model", None, 7, 123).generate("prompt")
    assert result.content == "generated"
    assert result.model == "provider-model"
    assert captured["url"] == "http://litellm:4000/v1/responses"
    assert captured["json"] == {"model": "configured-model", "input": [{"role": "user", "content": "prompt"}], "max_output_tokens": 123}


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_openai_compatible_adapter_normalizes_malformed_responses(monkeypatch, body) -> None:
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(200, body))
    with pytest.raises(GenerationError, match="malformed"):
        OpenAICompatibleGenerationAdapter("http://litellm/v1/chat/completions", "model", None).generate("prompt")


def test_openai_compatible_adapter_rejects_urls_without_a_supported_endpoint_suffix() -> None:
    with pytest.raises(GenerationError, match="full endpoint ending in /chat/completions or /responses"):
        OpenAICompatibleGenerationAdapter("http://litellm/v1", "model", None)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, {"error": {"message": "route missing"}}, "HTTP 404: route missing"),
        (500, {"message": "Authorization: Bearer secret-value failed"}, "HTTP 500: Authorization: Bearer [redacted] failed"),
    ],
)
def test_openai_compatible_adapter_normalizes_provider_http_failures(monkeypatch, status, body, expected) -> None:
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(status, body))
    with pytest.raises(GenerationError, match=re.escape(expected)):
        OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")


def test_openai_compatible_adapter_normalizes_timeout_with_endpoint_style(monkeypatch) -> None:
    def timed_out(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("httpx.post", timed_out)
    with pytest.raises(GenerationError, match="timed out for responses endpoint"):
        OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")
