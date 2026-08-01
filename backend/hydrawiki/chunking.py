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


def chunk_content(content: str, max_lines: int = 80, max_characters: int = 4000) -> list[Chunk]:
    """Split normalized UTF-8 text into stable, line-aware size-bounded chunks."""
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")
    if not content:
        return []
    lines = content.splitlines()
    result: list[Chunk] = []
    current_parts: list[str] = []
    current_characters = 0
    current_line_start = 1
    current_line_end = 0

    def append_chunk(text: str, line_start: int, line_end: int) -> None:
        result.append(Chunk(len(result), text, hashlib.sha256(text.encode()).hexdigest(), line_start, line_end))

    def flush() -> None:
        nonlocal current_parts, current_characters, current_line_end
        if current_parts:
            append_chunk("".join(current_parts), current_line_start, current_line_end)
            current_parts = []
            current_characters = 0
            current_line_end = 0

    for line_number, line in enumerate(lines, 1):
        rendered = line + ("\n" if line_number < len(lines) else "")
        if len(rendered) > max_characters:
            flush()
            for offset in range(0, len(rendered), max_characters):
                append_chunk(rendered[offset : offset + max_characters], line_number, line_number)
            continue
        if current_parts and (len(current_parts) >= max_lines or current_characters + len(rendered) > max_characters):
            flush()
        if not current_parts:
            current_line_start = line_number
        current_parts.append(rendered)
        current_characters += len(rendered)
        current_line_end = line_number
    flush()
    return result
