"""Phase 7 migration tests."""

from jarvis import migrate_safe


def test_backup_restore_list():
    b = migrate_safe.backup_json_files()
    assert isinstance(b, list)
    lst = migrate_safe.list_backups()
    assert isinstance(lst, list)
    # restore_latest_backup for non-existent returns None
    assert migrate_safe.restore_latest_backup("nope.json") is None
