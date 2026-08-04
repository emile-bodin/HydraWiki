import json

import pytest

from hydrawiki.wiki import WIKI_GROUPS, WikiGenerationError, _load_prompt_template, _parse_generated_wiki, _prompt


def test_wiki_v2_prompt_template_loads_and_renders() -> None:
    sources = [{"path": "src/app.py", "line_start": 10, "line_end": 14, "chunk_text": "def run(): pass"}]

    prompt = _prompt("Application overview", sources)

    assert prompt == _load_prompt_template().replace("__TITLE__", "Application overview").replace(
        "__SOURCE_EXCERPTS__", "--- src/app.py:10-14 ---\ndef run(): pass"
    )
    assert "Application overview" in prompt
    assert "Return JSON only" in prompt
    assert "exactly: content (non-empty string) and citations" in prompt
    assert "Every claim must be supported by at least one citation" in prompt
    assert "provided paths and line ranges" in prompt
    assert "exactly these five top-level sections" in prompt
    for heading in ("System context", "Architecture overview", "Main components", "Key workflows", "Constraints and failure behavior"):
        assert f"## {heading}" in prompt
    assert "### Purpose" in prompt
    assert "### Overview" in prompt
    assert "### Installation" in prompt
    assert "inline CSS" in prompt
    assert "--- src/app.py:10-14 ---" in prompt


def test_wiki_prompt_renders_literal_json_braces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hydrawiki.wiki._load_prompt_template",
        lambda: 'Title: __TITLE__\nReturn JSON like {"content": "...", "citations": []}\n__SOURCE_EXCERPTS__',
    )

    prompt = _prompt("Application overview", [{"path": "app.py", "line_start": 1, "line_end": 2, "chunk_text": "pass"}])

    assert prompt == 'Title: Application overview\nReturn JSON like {"content": "...", "citations": []}\n--- app.py:1-2 ---\npass'


def test_wiki_prompt_fails_clearly_when_required_placeholder_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hydrawiki.wiki._load_prompt_template", lambda: "Title: __TITLE__")

    with pytest.raises(WikiGenerationError, match="missing required placeholder.*__SOURCE_EXCERPTS__"):
        _prompt("Application overview", [])


def test_wiki_prompt_fails_clearly_when_template_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_template(*_args, **_kwargs):
        raise FileNotFoundError("missing prompt")

    monkeypatch.setattr("hydrawiki.wiki.resources.files", missing_template)

    with pytest.raises(WikiGenerationError, match="wiki-v2 prompt template could not be loaded"):
        _prompt("Application overview", [])


def test_generated_wiki_structure_is_source_derived_and_keeps_empty_groups() -> None:
    payload = {
        "structure": [
            {"key": key, "title": label, "pages": ([{"path": "concepts/service", "title": "Service"}] if key == "concepts" else [])}
            for key, label in WIKI_GROUPS
        ],
        "pages": [{"group": "concepts", "path": "concepts/service", "title": "Service", "content": "# Service", "citations": [{"path": "app.py", "line_start": 1, "line_end": 2}]}],
    }

    wiki = _parse_generated_wiki(json.dumps(payload), "ignored", "ignored")

    assert [group.key for group in wiki.structure] == [key for key, _label in WIKI_GROUPS]
    assert [group.pages for group in wiki.structure if group.key != "concepts"] == [[], [], [], []]
    assert [page.path for page in wiki.pages] == ["concepts/service"]
