from importlib.resources import files


def test_repository_lifecycle_migration_is_versioned_and_cascades_runs() -> None:
    migration = files("hydrawiki.migrations").joinpath("001_repository_lifecycle.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS repositories" in migration
    assert "CREATE TABLE IF NOT EXISTS ingestion_runs" in migration
    assert "REFERENCES repositories(id) ON DELETE CASCADE" in migration
    assert "repository_deletion_receipts" in migration


def test_manifest_delta_migration_persists_inventory_cache_and_classifications() -> None:
    migration = files("hydrawiki.migrations").joinpath("002_manifest_delta.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS source_files" in migration
    assert "CREATE TABLE IF NOT EXISTS content_cache" in migration
    assert "CREATE TABLE IF NOT EXISTS manifest_runs" in migration
    assert "CREATE TABLE IF NOT EXISTS manifest_entries" in migration
    assert "'missing'" in migration
    assert "UNIQUE (content_sha256, parser_version)" in migration
