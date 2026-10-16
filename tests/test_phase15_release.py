"""Phase 15 Release-readiness Tests (offline; artifact/metadata checks)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# 1
def test_version_defined_and_semver():
    from jarvis import __version__

    assert re.match(r"^\d+\.\d+\.\d+$", __version__), __version__
    print(f"✓ Test 1 PASSED: __version__ is semver ({__version__})")


# 2
def test_version_matches_setup_py():
    from jarvis import __version__

    setup_src = _read("setup.py")
    m = re.search(r'version\s*=\s*"([^"]+)"', setup_src)
    assert m, "version not found in setup.py"
    assert m.group(1) == __version__, f"setup.py {m.group(1)} != {__version__}"
    print("✓ Test 2 PASSED: setup.py version matches jarvis.__version__")


# 3
def test_required_release_artifacts_exist():
    required = [
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
        "RELEASING.md",
        "pyproject.toml",
        "setup.py",
        "MANIFEST.in",
        "requirements.txt",
        "requirements-dev.txt",
        "Makefile",
        ".env.example",
        ".github/workflows/ci.yml",
        "scripts/run_tests.py",
        "main.py",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    assert not missing, f"missing: {missing}"
    print("✓ Test 3 PASSED: all release artifacts present")


# 4
def test_license_is_mit():
    text = _read("LICENSE")
    assert "MIT License" in text
    assert "Copyright (c)" in text
    print("✓ Test 4 PASSED: MIT LICENSE present")


# 5
def test_pyproject_build_system_and_tools():
    text = _read("pyproject.toml")
    assert "[build-system]" in text
    assert "setuptools" in text
    assert "build-backend" in text
    assert "[tool.pytest.ini_options]" in text
    print("✓ Test 5 PASSED: pyproject build-system + tool config")


# 6
def test_manifest_includes_web_and_docs():
    text = _read("MANIFEST.in")
    assert "recursive-include web" in text
    assert "include README.md" in text
    assert "include LICENSE" in text
    assert "prune data" in text
    print("✓ Test 6 PASSED: MANIFEST.in ships web UI and docs")


# 7
def test_setup_entry_point_declared():
    text = _read("setup.py")
    assert "jarvis=jarvis.cli:cli" in text
    assert "install_requires" in text
    assert 'python_requires=">=3.9"' in text
    print("✓ Test 7 PASSED: console entry point + python_requires declared")


# 8
def test_ci_workflow_matrix():
    text = _read(".github/workflows/ci.yml")
    assert "scripts/run_tests.py" in text
    assert "python-version" in text
    for version in ("3.9", "3.10", "3.11", "3.12"):
        assert version in text
    print("✓ Test 8 PASSED: CI runs the suite across Python 3.9–3.12")


# 9
def test_makefile_targets():
    text = _read("Makefile")
    for target in ("test:", "lint:", "install:", "dist", "clean:"):
        assert target in text, f"missing target {target}"
    assert "scripts/run_tests.py" in text
    print("✓ Test 9 PASSED: Makefile has test/lint/install/dist/clean targets")


# 10
def test_changelog_has_all_phases():
    text = _read("CHANGELOG.md")
    for phase in ("Phase 9", "Phase 10", "Phase 11", "Phase 12", "Phase 13", "Phase 14"):
        assert phase in text, f"CHANGELOG missing {phase}"
    print("✓ Test 10 PASSED: CHANGELOG documents phases 9–14")


# 11
def test_readme_covers_key_sections():
    text = _read("README.md").lower()
    for section in ("install", "usage", "features", "test", "license"):
        assert section in text, f"README missing '{section}'"
    print("✓ Test 11 PASSED: README covers key sections")


# 12
def test_env_example_documents_providers():
    text = _read(".env.example")
    assert "JARVIS_PROVIDERS" in text
    assert "JARVIS_ATIF_URL" in text
    print("✓ Test 12 PASSED: .env.example documents configuration")


# 13
def test_no_stray_root_files():
    stray = [p.name for p in ROOT.glob("*.txt") if p.name not in ("requirements.txt", "requirements-dev.txt")]
    assert not stray, f"stray root .txt files: {stray}"
    assert not (ROOT / "test_file.txt").exists()
    print("✓ Test 13 PASSED: no stray root files")


# 14
def test_web_ui_present_and_referenced():
    assert (ROOT / "web" / "index.html").exists()
    assert (ROOT / "web" / "app.js").exists()
    assert (ROOT / "web" / "style.css").exists()
    assert (ROOT / "web" / "app.js").read_text(encoding="utf-8").count("/api/") >= 5
    print("✓ Test 14 PASSED: web UI assets present and wired to the API")


# 15
def test_test_runner_is_dependency_free():
    text = _read("scripts/run_tests.py")
    assert "importlib" in text and "inspect" in text
    assert "import pytest" not in text  # runner itself must not import pytest
    print("✓ Test 15 PASSED: test runner does not depend on pytest")


# 16
def test_app_reports_version():
    from fastapi.testclient import TestClient

    from jarvis import __version__
    from jarvis.app import app

    with TestClient(app) as c:
        body = c.get("/api/status").json()
    assert body["version"] == __version__
    print("✓ Test 16 PASSED: /api/status reports the release version")


# 17
def test_tool_registry_size_stable():
    from jarvis.tools import get_enhanced_registry

    count = len(get_enhanced_registry().list_tools())
    assert count >= 69, f"expected >= 69 tools, got {count}"
    print(f"✓ Test 17 PASSED: registry exposes {count} tools")
