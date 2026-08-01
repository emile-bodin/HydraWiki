from pathlib import Path


RUNBOOK = (Path(__file__).parents[2] / "docs" / "operations" / "backup-restore.md").read_text()


def test_restore_runbook_is_fail_closed_and_isolated() -> None:
    assert 'case "$project" in hydrawiki-restore-*' in RUNBOOK
    assert 'workspace_volume="${project}_workspace-data"' in RUNBOOK
    assert 'docker volume inspect "$workspace_volume"' in RUNBOOK
    assert 'test -z "$(find /target -mindepth 1 -maxdepth 1 -print -quit)"' in RUNBOOK
    assert 'rm -rf /target/*' not in RUNBOOK
    assert 'r.raise_for_status(); body=r.json(); sys.exit(0 if body.get(\\"status\\") == \\"ok\\" and body.get(\\"result\\") else 1)' in RUNBOOK
    assert 'diff -u "$backup_dir/schema-migrations.txt" -' in RUNBOOK


def test_backup_runbook_records_secret_free_provenance_and_quiesces_writers() -> None:
    assert '"${compose[@]}" stop api worker' in RUNBOOK
    for artifact in ('backup-timestamp.txt', 'compose.sha256', 'images.txt', 'schema-migrations.txt'):
        assert artifact in RUNBOOK
