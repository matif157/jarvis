"""Phase 6 security tests."""

from jarvis import security


def test_current_dir_safe():
    assert security.is_path_safe(".")


def test_project_safe():
    from pathlib import Path
    assert security.is_path_safe(str(Path(__file__).parent.parent))
