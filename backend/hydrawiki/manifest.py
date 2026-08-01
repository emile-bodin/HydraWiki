"""Phase-3 source manifest and transactional delta application."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator
from uuid import UUID, uuid4

from .config import Settings
from .persistence import Database
from .sources import LocalRepositoryAdapter, PublicGitRepositoryAdapter

PARSER_VERSION = "text-v1"
ELIGIBLE_SUFFIXES = frozenset(
    ".c .cc .cpp .css .go .h .hpp .html .java .js .json .jsx .md .py .rb .rs .sh .sql .toml .ts .tsx .txt .yaml .yml"
    .split()
)
IGNORED_DIRECTORIES = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"})


class ManifestError(RuntimeError):
    """A source scan could not produce a complete manifest."""


class ManifestBusyError(ManifestError):
    """Another process currently owns the single-ingest lease."""


@dataclass(frozen=True)
class ManifestFile:
    path: str
    content_sha256: str
    byte_size: int
    normalized_content: str


@dataclass(frozen=True)
class ManifestResult:
    run_id: UUID
    status: str
    classifications: dict[str, int]
    error: str | None = None


def normalize_relative_path(path: str) -> str:
    """Return the only path form persisted in manifests."""

    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        raise ManifestError(f"unsafe source path: {path}")
    return candidate.as_posix()


def sha256_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def repository_size_bytes(root: Path) -> int:
    """Count every regular source file, including excluded/non-indexable files."""

    if root.is_symlink() or not root.is_dir():
        raise ManifestError("source root is not a safe readable directory")
    total = 0

    def onerror(error: OSError) -> None:
        raise ManifestError(f"unable to inspect source directory: {error.filename or 'unknown'}") from error

    for current, directories, names in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        directories[:] = sorted(name for name in directories if not (Path(current) / name).is_symlink())
        for name in sorted(names):
            candidate = Path(current) / name
            if candidate.is_symlink():
                continue
            try:
                if candidate.is_file():
                    total += candidate.stat().st_size
            except OSError as exc:
                raise ManifestError(f"unable to inspect source file: {candidate.name}") from exc
    return total


def discover_eligible_files(root: Path, settings: Settings) -> list[ManifestFile]:
    """Discover and read eligible files in deterministic path order."""

    if root.is_symlink() or not root.is_dir():
        raise ManifestError("source root is not a safe readable directory")
    root = root.resolve()
    eligible_bytes = 0
    result: list[ManifestFile] = []
    def onerror(error: OSError) -> None:
        raise ManifestError(f"unable to inspect source directory: {error.filename or 'unknown'}") from error

    for current, directories, names in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        directories[:] = sorted(name for name in directories if name not in IGNORED_DIRECTORIES and not (Path(current) / name).is_symlink())
        for name in sorted(names):
            candidate = Path(current) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                size = candidate.stat().st_size
                if candidate.suffix.lower() not in ELIGIBLE_SUFFIXES:
                    continue
                if size > settings.max_source_file_size_bytes:
                    raise ManifestError(f"source-file size limit exceeded: {candidate.name}")
                if len(result) >= settings.max_source_files:
                    raise ManifestError("eligible source-file count limit exceeded")
                raw = candidate.read_bytes()
                if b"\x00" in raw:
                    continue
                normalized = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                eligible_bytes += len(normalized.encode("utf-8"))
                if eligible_bytes > settings.max_total_indexable_text_bytes:
                    raise ManifestError("total indexable text limit exceeded")
            except (OSError, UnicodeError) as exc:
                raise ManifestError(f"unable to read source file: {candidate.name}") from exc
            relative = normalize_relative_path(candidate.relative_to(root).as_posix())
            result.append(ManifestFile(relative, sha256_content(raw), len(raw), normalized))
    return sorted(result, key=lambda item: item.path)


def classify(current: dict[str, dict], discovered: list[ManifestFile]) -> list[tuple[str, str, ManifestFile | None]]:
    incoming = {item.path: item for item in discovered}
    rows: list[tuple[str, str, ManifestFile | None]] = []
    for path in sorted(set(current) | set(incoming)):
        old = current.get(path)
        new = incoming.get(path)
        if new is None:
            rows.append((path, "missing", None))
        elif old is None:
            rows.append((path, "new", new))
        elif old["content_sha256"] == new.content_sha256 and old.get("parser_version") == PARSER_VERSION:
            rows.append((path, "unchanged", new))
        else:
            rows.append((path, "changed", new))
    return rows


def _public_checkout(source: PublicGitRepositoryAdapter, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--no-tags", "--branch", source.selected_ref, source.url, str(destination)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ManifestError("public Git source could not be checked out") from exc
    return destination


def _scan_path(repository: dict, settings: Settings, run_id: UUID) -> Iterator[Path]:
    if repository["source_type"] == "local":
        yield LocalRepositoryAdapter(Path(settings.local_repositories_root), repository["source_value"]).path
        return
    source = PublicGitRepositoryAdapter(repository["source_value"], repository["selected_ref"])
    destination = Path(settings.workspace_root).resolve() / str(repository["id"]) / f"manifest-{run_id}"
    try:
        yield _public_checkout(source, destination)
    finally:
        shutil.rmtree(destination, ignore_errors=True)


class ManifestStore:
    def __init__(self, database: Database):
        self.database = database

    def start(self, repository_id: UUID) -> UUID:
        self.database.migrate()
        run_id = uuid4()
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE manifest_runs SET status = 'failed', error = 'manifest scan interrupted before completion', completed_at = now() WHERE repository_id = %s AND status = 'running'",
                (repository_id,),
            )
            connection.execute(
                "INSERT INTO manifest_runs (id, repository_id, status, parser_version) VALUES (%s, %s, 'running', %s)",
                (run_id, repository_id, PARSER_VERSION),
            )
        return run_id

    def get(self, run_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute("SELECT * FROM manifest_runs WHERE id = %s", (run_id,)).fetchone()

    def entries(self, run_id: UUID) -> list[dict]:
        self.database.migrate()
        with self.database.connection() as connection:
            return list(connection.execute("SELECT * FROM manifest_entries WHERE manifest_run_id = %s ORDER BY path", (run_id,)))

    def fail(self, run_id: UUID, error: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE manifest_runs SET status = 'failed', error = %s, completed_at = now() WHERE id = %s",
                (error[:2000], run_id),
            )

    def apply_success(self, repository_id: UUID, run_id: UUID, files: list[ManifestFile]) -> dict[str, int]:
        with self.database.connection() as connection:
            old_rows = list(connection.execute("SELECT * FROM source_files WHERE repository_id = %s", (repository_id,)))
            current = {row["path"]: row for row in old_rows}
            classified = classify(current, files)
            for path, kind, item in classified:
                connection.execute(
                    "INSERT INTO manifest_entries (manifest_run_id, path, content_sha256, byte_size, classification) VALUES (%s, %s, %s, %s, %s)",
                    (run_id, path, item.content_sha256 if item else None, item.byte_size if item else None, kind),
                )
                if kind == "missing":
                    connection.execute("DELETE FROM source_files WHERE repository_id = %s AND path = %s", (repository_id, path))
                    continue
                cache = connection.execute(
                    "SELECT id FROM content_cache WHERE content_sha256 = %s AND parser_version = %s",
                    (item.content_sha256, PARSER_VERSION),
                ).fetchone()
                if cache is None:
                    cache_id = uuid4()
                    connection.execute(
                        "INSERT INTO content_cache (id, content_sha256, parser_version, normalized_content, byte_size, line_count) VALUES (%s, %s, %s, %s, %s, %s)",
                        (cache_id, item.content_sha256, PARSER_VERSION, item.normalized_content, len(item.normalized_content.encode("utf-8")), item.normalized_content.count("\n") + 1),
                    )
                else:
                    cache_id = cache["id"]
                connection.execute(
                    "INSERT INTO source_files (repository_id, path, content_sha256, byte_size, content_cache_id, parser_version, last_manifest_run_id) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (repository_id, path) DO UPDATE SET content_sha256 = EXCLUDED.content_sha256, byte_size = EXCLUDED.byte_size, content_cache_id = EXCLUDED.content_cache_id, parser_version = EXCLUDED.parser_version, last_manifest_run_id = EXCLUDED.last_manifest_run_id",
                    (repository_id, path, item.content_sha256, item.byte_size, cache_id, PARSER_VERSION, run_id),
                )
            counts = {kind: sum(1 for _, actual, _ in classified if actual == kind) for kind in ("new", "changed", "unchanged", "missing")}
            connection.execute(
                "UPDATE manifest_runs SET status = 'succeeded', file_count = %s, total_bytes = %s, completed_at = now(), error = NULL WHERE id = %s",
                (len(files), sum(item.byte_size for item in files), run_id),
            )
            return counts


class ManifestLease:
    """A PostgreSQL session lock spanning the complete source scan and apply."""

    def __init__(self, database: Database):
        self.database = database
        self.connection = None

    def __enter__(self) -> "ManifestLease":
        self.connection_context = self.database.connection()
        self.connection = self.connection_context.__enter__()
        acquired = self.connection.execute("SELECT pg_try_advisory_lock(hashtext('hydrawiki.manifest-ingest')) AS acquired").fetchone()["acquired"]
        if not acquired:
            self.connection_context.__exit__(None, None, None)
            self.connection = None
            raise ManifestBusyError("another manifest scan is already running")
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        # Closing the session releases the advisory lock even after an
        # unexpected worker exception. Explicit unlock is best-effort only.
        if self.connection is not None:
            try:
                self.connection.execute("SELECT pg_advisory_unlock(hashtext('hydrawiki.manifest-ingest'))")
            finally:
                self.connection_context.__exit__(exception_type, exception, traceback)


def run_manifest(database: Database, settings: Settings, repository: dict) -> ManifestResult:
    with ManifestLease(database):
        store = ManifestStore(database)
        run_id = store.start(repository["id"])
        source_iter = _scan_path(repository, settings, run_id)
        try:
            root = next(source_iter)
            if repository_size_bytes(root) > settings.max_repository_size_bytes:
                raise ManifestError("repository size limit exceeded")
            files = discover_eligible_files(root, settings)
            counts = store.apply_success(repository["id"], run_id, files)
            return ManifestResult(run_id, "succeeded", counts)
        except Exception as exc:
            store.fail(run_id, str(exc))
            return ManifestResult(run_id, "failed", {}, str(exc))
        finally:
            source_iter.close()
