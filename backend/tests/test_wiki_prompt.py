import pytest

from hydrawiki.wiki import WikiGenerationError, _load_prompt_template, _prompt, _section_context


def test_wiki_v2_prompt_template_loads_and_renders() -> None:
    sources = [{"path": "src/app.py", "line_start": 10, "line_end": 14, "chunk_text": "def run(): pass"}]

    prompt = _prompt("Application overview", sources, "concepts/architecture")

    assert prompt == _load_prompt_template().replace("__TITLE__", "Application overview").replace("__SECTION_KEY__", "concepts").replace("__SECTION_LABEL__", "Concepts").replace("__SECTION_PURPOSE__", "Architecture, core concepts, component relationships, and design principles where supported by evidence.").replace("__SOURCE_EXCERPTS__", "--- src/app.py:10-14 ---\ndef run(): pass")
    assert "Application overview" in prompt
    assert "Return JSON only" in prompt
    assert "exactly: content (non-empty string) and citations" in prompt
    assert "Every claim must be supported by at least one citation" in prompt
    assert "provided paths and line ranges" in prompt
    assert "--- src/app.py:10-14 ---" in prompt
    assert "`concepts` (`Concepts`)" in prompt
    assert "Architecture, core concepts" in prompt


def test_wiki_prompt_renders_literal_json_braces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hydrawiki.wiki._load_prompt_template",
        lambda: 'Title: __TITLE__ __SECTION_KEY__ __SECTION_LABEL__ __SECTION_PURPOSE__\nReturn JSON like {"content": "...", "citations": []}\n__SOURCE_EXCERPTS__',
    )

    prompt = _prompt("Application overview", [{"path": "app.py", "line_start": 1, "line_end": 2, "chunk_text": "pass"}], "reference/api")

    assert prompt == 'Title: Application overview reference Reference Precise technical facts such as configuration, APIs, commands, options, and data structures where supported by evidence.\nReturn JSON like {"content": "...", "citations": []}\n--- app.py:1-2 ---\npass'


def test_wiki_prompt_fails_clearly_when_required_placeholder_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hydrawiki.wiki._load_prompt_template", lambda: "Title: __TITLE__")

    with pytest.raises(WikiGenerationError, match="missing required placeholder.*__SECTION_KEY__"):
        _prompt("Application overview", [], "get-started/overview")


def test_wiki_prompt_fails_clearly_when_template_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_template(*_args, **_kwargs):
        raise FileNotFoundError("missing prompt")

    monkeypatch.setattr("hydrawiki.wiki.resources.files", missing_template)

    with pytest.raises(WikiGenerationError, match="wiki-v2 prompt template could not be loaded"):
        _prompt("Application overview", [], "get-started/overview")


def test_section_context_uses_the_fixed_section_mapping() -> None:
    assert _section_context("workflows/publishing") == ("workflows", "Workflows", "End-to-end processes, sequence, states, decision points, and error handling where supported by evidence.")


@pytest.mark.parametrize("page_path, message", [("overview", "supported wiki section followed by a page slug"), ("unknown/overview", "unsupported wiki section prefix")])
def test_section_context_fails_closed_for_missing_or_unknown_prefix(page_path: str, message: str) -> None:
    with pytest.raises(WikiGenerationError, match=message):
        _section_context(page_path)
