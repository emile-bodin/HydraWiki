import httpx
import pytest

from hydrawiki.generation import GenerationError, OpenAICompatibleGenerationAdapter


def response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://litellm/v1/chat/completions"))


def test_openai_compatible_adapter_uses_configured_endpoint_model_and_optional_bearer_key(monkeypatch) -> None:
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured.update(kwargs)
        return response(200, {"model": "provider-model", "choices": [{"message": {"content": "generated"}}]})

    monkeypatch.setattr("httpx.post", fake_post)
    result = OpenAICompatibleGenerationAdapter("http://litellm:4000/v1/", "configured-model", "test-key", 7, 123).generate("prompt")
    assert result.content == "generated"
    assert result.model == "provider-model"
    assert captured["url"] == "http://litellm:4000/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["json"]["model"] == "configured-model"
    assert captured["json"]["max_tokens"] == 123


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_openai_compatible_adapter_normalizes_malformed_responses(monkeypatch, body) -> None:
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: response(200, body))
    with pytest.raises(GenerationError, match="malformed"):
        OpenAICompatibleGenerationAdapter("http://litellm/v1", "model", None).generate("prompt")
