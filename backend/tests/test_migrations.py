from importlib.resources import files


def test_repository_lifecycle_migration_is_versioned_and_cascades_runs() -> None:
    migration = files("hydrawiki.migrations").joinpath("001_repository_lifecycle.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS repositories" in migration
    assert "CREATE TABLE IF NOT EXISTS ingestion_runs" in migration
    assert "REFERENCES repositories(id) ON DELETE CASCADE" in migration
    assert "repository_deletion_receipts" in migration
