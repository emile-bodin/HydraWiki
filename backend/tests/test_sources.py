from pathlib import Path

import pytest

from hydrawiki.sources import LocalRepositoryAdapter, PublicGitRepositoryAdapter, SourceValidationError


def test_local_adapter_accepts_only_existing_paths_under_root(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    assert LocalRepositoryAdapter(tmp_path, "repo").path == tmp_path / "repo"
    for path in ("../repo", "/etc", "repo/../other", ""):
        with pytest.raises(SourceValidationError):
            LocalRepositoryAdapter(tmp_path, path)


def test_local_adapter_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "hydrawiki-outside-fixture"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(SourceValidationError):
        LocalRepositoryAdapter(tmp_path, "escape")


@pytest.mark.parametrize("url", ["file:///tmp/repo", "ssh://git@example.com/repo", "https://user:pass@example.com/repo", "https://127.0.0.1/repo"])
def test_public_git_rejects_non_public_urls(url: str) -> None:
    with pytest.raises(SourceValidationError):
        PublicGitRepositoryAdapter(url, "main")


@pytest.mark.parametrize("ref", ["", "../main", "main~1", "main branch", "-main"])
def test_public_git_rejects_invalid_refs(ref: str) -> None:
    with pytest.raises(SourceValidationError):
        PublicGitRepositoryAdapter("https://github.com/example/repo.git", ref)


def test_public_git_accepts_https_url_and_ref() -> None:
    source = PublicGitRepositoryAdapter("https://github.com/example/repo.git", "refs/heads/main")
    assert source.selected_ref == "refs/heads/main"
