"""Security tests."""

from jarvis import security, tools


def test_safe_path_allowed():
    import os
    from pathlib import Path

    p = str(Path.home() / "Downloads")
    assert security.is_path_safe(p)


def test_unsafe_path_blocked():
    assert not security.is_path_safe("/etc/shadow")


def test_fs_blocks_unsafe():
    reg = tools.get_enhanced_registry()
    res = reg.execute("fs.list", directory="/etc")
    assert not res.success
