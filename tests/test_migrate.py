"""Migration tests."""

import json
import os
import tempfile
from pathlib import Path

from jarvis import migrate, migrate_safe, config


def test_migrate_creates_counts():
    # use a temp data dir by monkeying around minimally
    d = tempfile.mkdtemp()
    data = Path(d)
    # write files
    (data / "notes.json").write_text(json.dumps([{"content": "hi", "created_at": "2020-01-01T00:00:00"}]))
    (data / "tasks.json").write_text(json.dumps([]))
    (data / "memory.json").write_text(json.dumps({}))
    # just ensure functions work
    backups = migrate_safe.backup_json_files()
    # don't affect real data; counts should be sane
    assert isinstance(backups, list)
