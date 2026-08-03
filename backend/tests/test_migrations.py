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


def test_wiki_generation_migration_persists_pages_artifacts_and_citations() -> None:
    migration = files("hydrawiki.migrations").joinpath("005_wiki_generation.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS wiki_pages" in migration
    assert "CREATE TABLE IF NOT EXISTS generation_artifacts" in migration
    assert "CREATE TABLE IF NOT EXISTS wiki_page_sources" in migration
    assert "line_end >= line_start" in migration


def test_mermaid_migration_persists_safe_or_failed_diagrams_only() -> None:
    migration = files("hydrawiki.migrations").joinpath("006_mermaid_diagrams.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS generation_diagrams" in migration
    assert "status IN ('safe', 'failed')" in migration
    assert "svg IS NOT NULL" in migration


def test_generation_failure_stage_migration_is_versioned() -> None:
    migration = files("hydrawiki.migrations").joinpath("007_generation_failure_stage.sql").read_text()
    assert "ALTER TABLE generation_runs ADD COLUMN IF NOT EXISTS failure_stage" in migration
