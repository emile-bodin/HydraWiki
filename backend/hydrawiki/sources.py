"""Validated repository source adapters. They never modify local source mounts."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class SourceValidationError(ValueError):
    """The requested source is outside the supported public contract."""


@dataclass(frozen=True)
class LocalRepositoryAdapter:
    root: Path
    relative_path: str

    def __post_init__(self) -> None:
        root = self.root.expanduser().resolve()
        raw = self.relative_path.replace("\\", "/")
        candidate = Path(raw)
        if not raw or candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
            raise SourceValidationError("local repository path must be a non-empty relative path without traversal")
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SourceValidationError("local repository path escapes LOCAL_REPOSITORIES_ROOT") from exc
        if not resolved.is_dir():
            raise SourceValidationError("local repository path must identify a mounted directory")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "relative_path", candidate.as_posix())

    @property
    def path(self) -> Path:
        return self.root / self.relative_path


_REF_FORBIDDEN = re.compile(r"[\s~^:?*\\\[\x00-\x1f]")


@dataclass(frozen=True)
class PublicGitRepositoryAdapter:
    url: str
    selected_ref: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SourceValidationError("public Git URL must be an HTTPS URL without credentials")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
            raise SourceValidationError("public Git URL must not target a private address")
        if not parsed.path or parsed.path == "/":
            raise SourceValidationError("public Git URL must identify a repository")
        ref = self.selected_ref.strip()
        if not ref or ref.startswith("-") or ".." in ref or _REF_FORBIDDEN.search(ref):
            raise SourceValidationError("selected Git ref is invalid")
        object.__setattr__(self, "selected_ref", ref)
