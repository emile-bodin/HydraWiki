"""Bounded local Mermaid rendering and an intentionally narrow SVG boundary."""
from __future__ import annotations

import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class MermaidError(RuntimeError):
    pass


_FENCE = re.compile(r"^```mermaid[ \t]*\r?\n(.*?)(?:\r?\n)?```[ \t]*$", re.MULTILINE | re.DOTALL)
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
_TEXT = re.compile(r"^[\w .,:;()#+/%'\-–]+$", re.UNICODE)
_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "marker", "defs", "title", "desc", "style"}
_COMMON = {"id", "class", "fill", "stroke", "stroke-width", "opacity", "transform", "aria-roledescription", "role"}
_ATTRS = {"svg": {"width", "height", "viewBox", "xmlns", "aria-labelledby"}, "path": {"d", "marker-end", "marker-start"}, "rect": {"x", "y", "width", "height", "rx", "ry"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"}, "line": {"x1", "x2", "y1", "y2"}, "polyline": {"points"}, "polygon": {"points"}, "text": {"x", "y", "text-anchor", "font-family", "font-size"}, "tspan": {"x", "y", "dy"}, "marker": {"markerWidth", "markerHeight", "refX", "refY", "orient", "viewBox"}}


@dataclass(frozen=True)
class RenderedDiagram:
    source: str
    svg: str


def extract_mermaid_sources(content: str) -> list[str]:
    return [match.group(1).strip() for match in _FENCE.finditer(content)]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sanitize_svg(svg: str, max_bytes: int) -> str:
    """Reject, rather than repair, renderer output outside the inert SVG subset."""
    if not svg or len(svg.encode()) > max_bytes:
        raise MermaidError("Mermaid renderer produced an oversized SVG")
    if re.search(r"<!DOCTYPE|<!ENTITY|<script|on[a-z]+\s*=|javascript:|<foreignObject", svg, re.I):
        raise MermaidError("Mermaid renderer produced unsafe SVG")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise MermaidError("Mermaid renderer produced invalid SVG") from exc
    if _local(root.tag) != "svg":
        raise MermaidError("Mermaid renderer did not produce an SVG root")
    for element in root.iter():
        tag = _local(element.tag)
        if tag not in _TAGS:
            raise MermaidError("Mermaid renderer produced unsupported SVG content")
        for name, value in element.attrib.items():
            local = _local(name)
            if local not in _COMMON | _ATTRS.get(tag, set()) or not _TEXT.fullmatch(value):
                raise MermaidError("Mermaid renderer produced unsafe SVG attributes")
            if local in {"id", "class", "aria-labelledby"} and not _NAME.fullmatch(value):
                raise MermaidError("Mermaid renderer produced unsafe SVG identifiers")
            if local in {"marker-end", "marker-start"} and not re.fullmatch(r"url\(#[A-Za-z_][A-Za-z0-9_.:-]{0,127}\)", value):
                raise MermaidError("Mermaid renderer produced unsafe SVG references")
        if tag == "style" and re.search(r"url\s*\(|@|expression|behavior|binding|<", element.text or "", re.I):
            raise MermaidError("Mermaid renderer produced unsafe SVG styles")
        if tag != "style" and element.text and not _TEXT.fullmatch(element.text.strip()):
            raise MermaidError("Mermaid renderer produced unsafe SVG text")
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="unicode")


class MermaidRenderer:
    def __init__(self, command: str, timeout_seconds: float, max_source_characters: int, max_svg_bytes: int):
        self.command, self.timeout_seconds = command, timeout_seconds
        self.max_source_characters, self.max_svg_bytes = max_source_characters, max_svg_bytes

    def render(self, source: str) -> RenderedDiagram:
        if not source.strip() or len(source) > self.max_source_characters:
            raise MermaidError("Mermaid source exceeds the configured limit")
        with tempfile.TemporaryDirectory(prefix="hydrawiki-mermaid-") as directory:
            root = Path(directory)
            input_path, output_path, config_path, browser_path = root / "diagram.mmd", root / "diagram.svg", root / "config.json", root / "browser.json"
            input_path.write_text(source, encoding="utf-8")
            config_path.write_text('{"securityLevel":"strict","flowchart":{"htmlLabels":false}}', encoding="utf-8")
            browser_path.write_text('{"args":["--no-sandbox"]}', encoding="utf-8")
            try:
                subprocess.run([self.command, "--input", str(input_path), "--output", str(output_path), "--outputFormat", "svg", "--configFile", str(config_path), "--puppeteerConfigFile", str(browser_path)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=self.timeout_seconds, cwd=root, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium"})
            except subprocess.TimeoutExpired as exc:
                raise MermaidError("Mermaid rendering timed out") from exc
            except FileNotFoundError as exc:
                raise MermaidError("Mermaid renderer is unavailable") from exc
            except subprocess.CalledProcessError as exc:
                raise MermaidError("Mermaid source failed server-side validation") from exc
            try:
                svg = output_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise MermaidError("Mermaid renderer produced no SVG") from exc
        return RenderedDiagram(source, sanitize_svg(svg, self.max_svg_bytes))
