"""Bounded local Mermaid rendering and an intentionally narrow SVG boundary."""
from __future__ import annotations

import json
import re
import os
import pwd
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


class MermaidError(RuntimeError):
    pass


_FENCE = re.compile(r"^```mermaid[ \t]*\r?\n(.*?)(?:\r?\n)?```[ \t]*$", re.MULTILINE | re.DOTALL)
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_DIRECTIVE = re.compile(r"(?m)^\s*%%\{")
_PRESENTATION = re.compile(r"(?im)^\s*(?:classDef|class|style|linkStyle|click)\b")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
_TEXT = re.compile(r"^[\w .,:;()#+/%'\-–]+$", re.UNICODE)
_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "marker", "defs", "title", "desc"}
_COMMON = {"id", "class", "fill", "stroke", "stroke-width", "opacity", "transform", "aria-roledescription", "role"}
_ATTRS = {"svg": {"width", "height", "viewBox", "xmlns", "aria-labelledby"}, "path": {"d", "marker-end", "marker-start"}, "rect": {"x", "y", "width", "height", "rx", "ry"}, "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"}, "line": {"x1", "x2", "y1", "y2"}, "polyline": {"points"}, "polygon": {"points"}, "text": {"x", "y", "text-anchor", "font-family", "font-size"}, "tspan": {"x", "y", "dx", "dy", "text-anchor"}, "marker": {"markerWidth", "markerHeight", "markerUnits", "refX", "refY", "orient", "viewBox"}}
_DEFAULT_SHAPE_PRESENTATION = {"fill": "white", "stroke": "#333", "stroke-width": "1"}
_ROOT_STYLE_VALUE = re.compile(r"(?:max-width:\s*([0-9]{1,5}(?:\.[0-9]{1,4})?)px|background-color:\s*white)")
_PAINT = re.compile(r"(?:none|currentColor|transparent|white|black|#[0-9A-Fa-f]{3,8})")
_STROKE_WIDTH = re.compile(r"(?:0|[0-9]{1,3}(?:\.[0-9]{1,3})?)(?:px)?")
_OPACITY = re.compile(r"(?:0(?:\.\d{1,3})?|1(?:\.0{1,3})?)")
_TRANSFORM_NUMBER = r"-?[0-9]{1,5}(?:\.\d{1,16})?"
_TRANSFORM = re.compile(rf"(?:translate|scale|rotate)\({_TRANSFORM_NUMBER}(?:[ ,]+{_TRANSFORM_NUMBER}){{0,2}}\)(?:\s+(?:translate|scale|rotate)\({_TRANSFORM_NUMBER}(?:[ ,]+{_TRANSFORM_NUMBER}){{0,2}}\)){{0,7}}")
_SITE_CONFIG = {
    "securityLevel": "strict",
    "htmlLabels": False,
    "theme": "default",
    "look": "classic",
    "layout": "dagre",
    "secure": [
        "securityLevel", "htmlLabels", "theme", "themeVariables", "themeCSS", "look", "layout",
        "fontFamily", "fontSize", "wrap", "markdownAutoWrap", "flowchart", "sequence", "gantt",
        "state", "er", "class", "journey", "pie", "requirement", "gitGraph", "mindmap", "timeline",
        "quadrantChart", "xyChart", "sankey", "block", "packet", "architecture", "kanban", "radar",
    ],
}


@dataclass(frozen=True)
class RenderedDiagram:
    source: str
    svg: str


def extract_mermaid_sources(content: str) -> list[str]:
    return [match.group(1).strip() for match in _FENCE.finditer(content)]


def validate_mermaid_source(source: str) -> None:
    """Accept portable Mermaid structure, but reject presentation controls we cannot publish safely."""
    frontmatter = _FRONTMATTER.match(source)
    if frontmatter and re.search(r"(?m)^\s*config\s*:", frontmatter.group(1)):
        raise MermaidError("Mermaid per-diagram configuration is not supported")
    if _DIRECTIVE.search(source):
        raise MermaidError("Mermaid directives are not supported; use standard diagram syntax")
    if _PRESENTATION.search(source):
        raise MermaidError("Mermaid presentation syntax is not supported")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_root_style(value: str) -> None:
    """Allow only Mermaid CLI's layout width and opaque white canvas declarations."""
    declarations = value.split(";")
    if declarations[-1] == "":
        declarations.pop()
    if not declarations or len(declarations) > 2:
        raise MermaidError("Mermaid renderer produced unsafe root SVG styles")
    seen: set[str] = set()
    for declaration in declarations:
        declaration = declaration.strip()
        match = _ROOT_STYLE_VALUE.fullmatch(declaration)
        if match is None:
            raise MermaidError("Mermaid renderer produced unsafe root SVG styles")
        property_name = declaration.split(":", 1)[0]
        if property_name in seen or (match.group(1) is not None and float(match.group(1)) > 10000):
            raise MermaidError("Mermaid renderer produced unsafe root SVG styles")
        seen.add(property_name)


def _validate_presentation_attribute(name: str, value: str) -> None:
    valid = {
        "fill": _PAINT,
        "stroke": _PAINT,
        "stroke-width": _STROKE_WIDTH,
        "opacity": _OPACITY,
        "transform": _TRANSFORM,
    }[name]
    if valid.fullmatch(value) is None:
        raise MermaidError("Mermaid renderer produced unsafe SVG presentation attributes")


def sanitize_svg(svg: str, max_bytes: int, *, strip_renderer_presentation: bool = False) -> str:
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
    if strip_renderer_presentation:
        # Mermaid CLI emits CSS and SVG filters even with strict mode. Its
        # locked configuration prevents diagram input from altering these
        # renderer-owned layers; remove them before inert-SVG validation.
        for parent in root.iter():
            for child in list(parent):
                if _local(child.tag) in {"style", "filter"}:
                    parent.remove(child)
        for element in root.iter():
            for name in list(element.attrib):
                local = _local(name)
                if local == "style" or local.startswith("data-") or local in {"class", "font-style", "font-weight"}:
                    del element.attrib[name]
            if _local(element.tag) in {"rect", "circle", "ellipse", "polygon"}:
                for name, value in _DEFAULT_SHAPE_PRESENTATION.items():
                    element.attrib.setdefault(name, value)
    for element in root.iter():
        tag = _local(element.tag)
        if tag not in _TAGS:
            raise MermaidError("Mermaid renderer produced unsupported SVG content")
        for name, value in element.attrib.items():
            local = _local(name)
            if tag == "svg" and local == "style":
                _validate_root_style(value)
                continue
            if local not in _COMMON | _ATTRS.get(tag, set()) or not _TEXT.fullmatch(value):
                raise MermaidError("Mermaid renderer produced unsafe SVG attributes")
            if "url(" in value.lower() and local not in {"marker-end", "marker-start"}:
                raise MermaidError("Mermaid renderer produced unsafe SVG references")
            if local in {"fill", "stroke", "stroke-width", "opacity", "transform"}:
                _validate_presentation_attribute(local, value)
            if local in {"id", "class", "aria-labelledby"} and not _NAME.fullmatch(value):
                raise MermaidError("Mermaid renderer produced unsafe SVG identifiers")
            if local in {"marker-end", "marker-start"} and not re.fullmatch(r"url\(#[A-Za-z_][A-Za-z0-9_.:-]{0,127}\)", value):
                raise MermaidError("Mermaid renderer produced unsafe SVG references")
        if element.text and not _TEXT.fullmatch(element.text.strip()):
            raise MermaidError("Mermaid renderer produced unsafe SVG text")
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    return ET.tostring(root, encoding="unicode")


class MermaidRenderer:
    def __init__(self, command: str, timeout_seconds: float, max_source_characters: int, max_svg_bytes: int, user: str = "hydrawiki-renderer"):
        self.command, self.timeout_seconds = command, timeout_seconds
        self.max_source_characters, self.max_svg_bytes = max_source_characters, max_svg_bytes
        self.user = user

    def render(self, source: str) -> RenderedDiagram:
        if not source.strip() or len(source) > self.max_source_characters:
            raise MermaidError("Mermaid source exceeds the configured limit")
        validate_mermaid_source(source)
        try:
            renderer_user = pwd.getpwnam(self.user)
        except KeyError as exc:
            raise MermaidError("Mermaid sandbox user is unavailable") from exc
        with tempfile.TemporaryDirectory(prefix="hydrawiki-mermaid-") as directory:
            root = Path(directory)
            os.chown(root, renderer_user.pw_uid, renderer_user.pw_gid)
            input_path, output_path, config_path, browser_path = root / "diagram.mmd", root / "diagram.svg", root / "config.json", root / "browser.json"
            input_path.write_text(source, encoding="utf-8")
            config_path.write_text(json.dumps(_SITE_CONFIG, separators=(",", ":")), encoding="utf-8")
            browser_path.write_text("{}", encoding="utf-8")
            for path in (input_path, config_path, browser_path):
                os.chown(path, renderer_user.pw_uid, renderer_user.pw_gid)
            def drop_privileges() -> None:
                os.setgroups([])
                os.setgid(renderer_user.pw_gid)
                os.setuid(renderer_user.pw_uid)
            try:
                subprocess.run([self.command, "--input", str(input_path), "--output", str(output_path), "--outputFormat", "svg", "--configFile", str(config_path), "--puppeteerConfigFile", str(browser_path)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=self.timeout_seconds, cwd=root, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium"}, preexec_fn=drop_privileges)
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
        return RenderedDiagram(source, sanitize_svg(svg, self.max_svg_bytes, strip_renderer_presentation=True))
