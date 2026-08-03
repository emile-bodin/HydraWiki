import subprocess
import shutil
from types import SimpleNamespace

import pytest

from hydrawiki.mermaid import MermaidError, MermaidRenderer, sanitize_svg


SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><text x="1" y="2">safe</text></svg>'


def test_renderer_publishes_only_validated_safe_svg(monkeypatch):
    def fake_run(command, **_kwargs):
        from pathlib import Path
        assert "--no-sandbox" not in command
        browser_config = Path(command[command.index("--puppeteerConfigFile") + 1]).read_text()
        assert "no-sandbox" not in browser_config
        assert callable(_kwargs["preexec_fn"])
        Path(command[command.index("--output") + 1]).write_text(SAFE_SVG)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("hydrawiki.mermaid.subprocess.run", fake_run)
    monkeypatch.setattr("hydrawiki.mermaid.pwd.getpwnam", lambda _user: SimpleNamespace(pw_uid=12345, pw_gid=12345))
    monkeypatch.setattr("hydrawiki.mermaid.os.chown", lambda *_args: None)
    rendered = MermaidRenderer("mmdc", 1, 100, 1000).render("flowchart TD\nA-->B")
    assert "<svg" in rendered.svg


def test_standard_mermaid_root_style_is_an_inert_safe_subset():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" style="max-width: 86.6562px; background-color: white;"><text x="1" y="2">safe</text></svg>'
    assert 'style="max-width: 86.6562px; background-color: white;"' in sanitize_svg(svg, 1000)


def test_renderer_precision_transform_is_an_inert_safe_subset():
    svg = '<svg><g transform="translate(123.765625, 239.29999923706055)" /></svg>'
    assert 'transform="translate(123.765625, 239.29999923706055)"' in sanitize_svg(svg, 1000)


def test_renderer_style_removal_keeps_nodes_visible_with_safe_defaults():
    svg = '<svg><style>.node rect { fill: #ececff; }</style><g class="node"><rect width="100" height="40" /><text x="1" y="2">API</text></g></svg>'
    sanitized = sanitize_svg(svg, 1000, strip_renderer_presentation=True)
    assert "<style" not in sanitized
    assert 'class=' not in sanitized
    assert '<rect width="100" height="40" fill="white" stroke="#333" stroke-width="1"' in sanitized


@pytest.mark.skipif(shutil.which("mmdc") is None, reason="real Mermaid CLI unavailable; run the container validation command documented in the PR")
def test_real_pinned_mermaid_cli_output_is_safe():
    renderer = MermaidRenderer("mmdc", 15, 1_000, 2_000_000, user="hydrawiki-renderer")
    rendered = renderer.render("flowchart TD\nA-->B")
    assert "<svg" in rendered.svg
    assert "style=" in rendered.svg


@pytest.mark.parametrize("svg", ["<svg><script>alert(1)</script></svg>", '<svg><image href="https://example.invalid/x" /></svg>'])
def test_unsafe_renderer_svg_is_rejected(svg):
    with pytest.raises(MermaidError, match="unsafe|unsupported"):
        sanitize_svg(svg, 1000)


@pytest.mark.parametrize("attribute", ["fill", "stroke"])
def test_external_url_paint_references_are_rejected(attribute):
    with pytest.raises(MermaidError, match="unsafe SVG references|unsafe SVG presentation"):
        sanitize_svg(f'<svg><path d="M 0 0" {attribute}="url(https://example.invalid/pattern)" /></svg>', 1000)


def test_css_escaped_url_is_rejected_with_style_element():
    with pytest.raises(MermaidError, match="unsupported"):
        sanitize_svg('<svg><style>.x{fill:u\\72l(https://example.invalid/x)}</style></svg>', 1000)


@pytest.mark.parametrize("style", ["color: red", "max-width: url(https://example.invalid/x)", "max-width: u\\72l(https://example.invalid/x)", "background-color: transparent", "max-width: 1px; --x: y"])
def test_root_style_rejects_unknown_values_and_css_escapes(style):
    with pytest.raises(MermaidError, match="unsafe root SVG styles"):
        sanitize_svg(f'<svg style="{style}" />', 1000)


def test_timeout_is_a_render_failure(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("mmdc", 1)

    monkeypatch.setattr("hydrawiki.mermaid.subprocess.run", timeout)
    monkeypatch.setattr("hydrawiki.mermaid.pwd.getpwnam", lambda _user: SimpleNamespace(pw_uid=12345, pw_gid=12345))
    monkeypatch.setattr("hydrawiki.mermaid.os.chown", lambda *_args: None)
    with pytest.raises(MermaidError, match="timed out"):
        MermaidRenderer("mmdc", 1, 100, 1000).render("flowchart TD\nA-->B")


def test_missing_sandbox_user_fails_closed(monkeypatch):
    monkeypatch.setattr("hydrawiki.mermaid.pwd.getpwnam", lambda _user: (_ for _ in ()).throw(KeyError))
    with pytest.raises(MermaidError, match="sandbox user is unavailable"):
        MermaidRenderer("mmdc", 1, 100, 1000).render("flowchart TD\nA-->B")
