"""Deterministic, line-aware source chunking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    content_hash: str
    line_start: int
    line_end: int


def chunk_content(content: str, max_lines: int = 80) -> list[Chunk]:
    """Split normalized UTF-8 text into stable, non-overlapping line ranges."""
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    if not content:
        return []
    lines = content.splitlines()
    result = []
    for ordinal, offset in enumerate(range(0, len(lines), max_lines)):
        part = lines[offset : offset + max_lines]
        text = "\n".join(part)
        if offset + len(part) < len(lines):
            text += "\n"
        result.append(Chunk(ordinal, text, hashlib.sha256(text.encode()).hexdigest(), offset + 1, offset + len(part)))
    return result
