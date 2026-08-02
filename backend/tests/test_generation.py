import re

import httpx
import pytest

from hydrawiki.generation import GenerationError, OpenAICompatibleGenerationAdapter


def response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://litellm/v1/chat/completions"))


def sse_response(body: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/event-stream; charset=utf-8"},
        request=httpx.Request("POST", "http://litellm/v1/responses"),
    )


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


def test_openai_compatible_adapter_parses_responses_sse_deltas_in_order(monkeypatch) -> None:
    stream = "\n".join(
        [
            ": keep-alive",
            'data: {"type":"response.created","response":{"model":"provider-model"}}',
            'data: {"type":"response.output_text.delta","delta":"first "}',
            'data: {"type":"response.output_text.delta","delta":"second"}',
            'data: {"type":"response.output_text.done","text":"first second"}',
            'data: [DONE]',
        ]
    )
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: sse_response(stream))

    result = OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")

    assert result.content == "first second"
    assert result.model == "model"


def test_openai_compatible_adapter_parses_responses_sse_completed_output(monkeypatch) -> None:
    stream = 'data: {"type":"response.completed","response":{"model":"provider-model","output":[{"type":"message","content":[{"type":"output_text","text":"completed text"}]}]}}\n'
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: sse_response(stream))

    result = OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")

    assert result.content == "completed text"
    assert result.model == "provider-model"


def test_openai_compatible_adapter_fails_closed_for_responses_sse_without_text(monkeypatch) -> None:
    stream = 'data: {"type":"response.created"}\ndata: [DONE]\n'
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: sse_response(stream))

    with pytest.raises(GenerationError, match="malformed"):
        OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")


def test_openai_compatible_adapter_sanitizes_responses_sse_provider_error(monkeypatch) -> None:
    stream = 'data: {"type":"error","error":{"message":"Authorization: Bearer secret-value failed"}}\n'
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: sse_response(stream))

    with pytest.raises(GenerationError, match=re.escape("generation provider returned an error: Authorization: Bearer [redacted] failed")):
        OpenAICompatibleGenerationAdapter("http://litellm/v1/responses", "model", None).generate("prompt")


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
