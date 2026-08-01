import subprocess

import pytest

from hydrawiki.mermaid import MermaidError, MermaidRenderer, sanitize_svg


SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="2">safe</text></svg>'


def test_renderer_publishes_only_validated_safe_svg(monkeypatch):
    def fake_run(command, **_kwargs):
        command[command.index("--output") + 1]
        from pathlib import Path
        Path(command[command.index("--output") + 1]).write_text(SAFE_SVG)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("hydrawiki.mermaid.subprocess.run", fake_run)
    rendered = MermaidRenderer("mmdc", 1, 100, 1000).render("flowchart TD\nA-->B")
    assert "<svg" in rendered.svg


@pytest.mark.parametrize("svg", ["<svg><script>alert(1)</script></svg>", '<svg><image href="https://example.invalid/x" /></svg>'])
def test_unsafe_renderer_svg_is_rejected(svg):
    with pytest.raises(MermaidError, match="unsafe|unsupported"):
        sanitize_svg(svg, 1000)


def test_timeout_is_a_render_failure(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("mmdc", 1)

    monkeypatch.setattr("hydrawiki.mermaid.subprocess.run", timeout)
    with pytest.raises(MermaidError, match="timed out"):
        MermaidRenderer("mmdc", 1, 100, 1000).render("flowchart TD\nA-->B")
