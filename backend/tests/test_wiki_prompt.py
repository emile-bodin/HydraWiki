import pytest

from hydrawiki.wiki import WikiGenerationError, _load_prompt_template, _prompt


def test_wiki_v1_prompt_template_loads_and_renders() -> None:
    sources = [{"path": "src/app.py", "line_start": 10, "line_end": 14, "chunk_text": "def run(): pass"}]

    prompt = _prompt("Application overview", sources)

    assert prompt == _load_prompt_template().format(
        title="Application overview",
        source_excerpts="--- src/app.py:10-14 ---\ndef run(): pass",
    )
    assert "Application overview" in prompt
    assert "Return JSON only" in prompt
    assert "exactly: content (non-empty string) and citations" in prompt
    assert "Every claim must be supported by at least one citation" in prompt
    assert "provided paths and line ranges" in prompt
    assert "--- src/app.py:10-14 ---" in prompt


def test_wiki_prompt_fails_clearly_when_template_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_template(*_args, **_kwargs):
        raise FileNotFoundError("missing prompt")

    monkeypatch.setattr("hydrawiki.wiki.resources.files", missing_template)

    with pytest.raises(WikiGenerationError, match="wiki-v1 prompt template could not be loaded"):
        _prompt("Application overview", [])
