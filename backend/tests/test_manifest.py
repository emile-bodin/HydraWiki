from pathlib import Path

import pytest

from hydrawiki.config import Settings
from hydrawiki.manifest import ManifestError, _public_checkout, classify, discover_eligible_files, normalize_relative_path, repository_size_bytes, sha256_content
from hydrawiki.sources import PublicGitRepositoryAdapter


def settings(**overrides) -> Settings:
    values = {"database_url": "postgresql://example/example", "qdrant_url": "http://qdrant:6333", **overrides}
    return Settings(**values)


def test_path_normalization_and_sha256_are_deterministic() -> None:
    assert normalize_relative_path("src\\main.py") == "src/main.py"
    assert sha256_content(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    with pytest.raises(ManifestError):
        normalize_relative_path("../main.py")


def test_eligible_discovery_filters_sorts_and_normalizes(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("z\r\n")
    (tmp_path / "a.txt").write_text("a\n")
    (tmp_path / "binary.bin").write_bytes(b"\x00ignored")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("ignored")
    found = discover_eligible_files(tmp_path, settings())
    assert [item.path for item in found] == ["a.txt", "z.py"]
    assert found[-1].normalized_content == "z\n"


def test_classification_covers_new_changed_unchanged_and_missing() -> None:
    old = {
        "same.py": {"content_sha256": sha256_content(b"same"), "parser_version": "text-v1"},
        "changed.py": {"content_sha256": sha256_content(b"old"), "parser_version": "text-v1"},
        "gone.py": {"content_sha256": sha256_content(b"gone"), "parser_version": "text-v1"},
    }
    from hydrawiki.manifest import ManifestFile

    current = [
        ManifestFile("same.py", sha256_content(b"same"), 4, "same"),
        ManifestFile("changed.py", sha256_content(b"new"), 3, "new"),
        ManifestFile("new.py", sha256_content(b"new"), 3, "new"),
    ]
    assert [(path, kind) for path, kind, _ in classify(old, current)] == [
        ("changed.py", "changed"),
        ("gone.py", "missing"),
        ("new.py", "new"),
        ("same.py", "unchanged"),
    ]


def test_limits_fail_before_any_delta_can_be_applied(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("12345")
    with pytest.raises(ManifestError, match="source-file size"):
        discover_eligible_files(tmp_path, settings(max_source_file_size_bytes=4))


def test_repository_size_counts_excluded_directories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "pack.bin").write_bytes(b"12345")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.bin").write_bytes(b"123456")
    assert repository_size_bytes(tmp_path) == 11
    assert repository_size_bytes(tmp_path) > 10


def test_public_git_checkout_uses_validated_url_and_ref_without_network(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).mkdir()

    monkeypatch.setattr("hydrawiki.manifest.subprocess.run", fake_run)
    source = PublicGitRepositoryAdapter("https://github.com/example/repository.git", "refs/heads/main")
    destination = _public_checkout(source, tmp_path / "checkout")
    assert destination.is_dir()
    assert calls[0][0][0:6] == ["git", "clone", "--depth", "1", "--no-tags", "--branch"]
    assert calls[0][0][-3:] == ["refs/heads/main", source.url, str(destination)]
