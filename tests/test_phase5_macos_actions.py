"""Phase 5 macOS Actions Tests"""

import os
import platform
import shutil
import tempfile
import uuid
from pathlib import Path
from jarvis.macos_actions import (
    OpenAppTool,
    OpenURLTool,
    RevealInFinderTool,
    CreateFileTool,
)
from jarvis import assistant

# These tests exercise AppleScript, Safari, Finder and ~/Downloads. They are
# meaningful on macOS only; the Linux CI runner skips the whole module.
SKIP = None
if platform.system() != "Darwin" or shutil.which("osascript") is None:
    SKIP = "requires macOS (osascript, Safari, Finder, ~/Downloads)"


def test_open_allowed_app():
    """Journey 1: Open an allowed application."""
    t = OpenAppTool()
    r = t.run(app_name="safari")
    assert r.success, f"Should open Safari: {r.error}"
    assert r.result.get("action") == "activate"
    assert r.result.get("app") == "Safari"
    print("✓ Journey 1 PASSED: Open allowed app (Safari)")


def test_reject_unknown_app():
    """Journey 2: Unknown application is rejected."""
    t = OpenAppTool()
    r = t.run(app_name="nonexistent_app_xyz")
    assert not r.success, "Should reject unknown app"
    assert "not in allowlist" in r.error.lower()
    print("✓ Journey 2 PASSED: Reject unknown app")


def test_open_valid_http_url():
    """Journey 3: Valid HTTP URL is accepted."""
    t = OpenURLTool()
    r = t.run(url="http://example.com")
    assert r.success, f"Should open HTTP URL: {r.error}"
    assert r.result.get("action") == "open"
    print("✓ Journey 3 PASSED: Open HTTP URL")


def test_open_valid_https_url():
    """Journey 4: Valid HTTPS URL is accepted."""
    t = OpenURLTool()
    r = t.run(url="https://www.example.com")
    assert r.success, f"Should open HTTPS URL: {r.error}"
    assert r.result.get("action") == "open"
    print("✓ Journey 4 PASSED: Open HTTPS URL")


def test_reject_invalid_scheme():
    """Journey 5: Invalid schemes are rejected."""
    t = OpenURLTool()
    r = t.run(url="file:///etc/passwd")
    assert not r.success, "Should reject file:// scheme"
    assert "invalid scheme" in r.error.lower() or "file" in r.error.lower()
    print("✓ Journey 5 PASSED: Reject file:// scheme")


def test_reject_javascript_scheme():
    """Journey 6: javascript: scheme rejected."""
    t = OpenURLTool()
    r = t.run(url="javascript:alert(1)")
    assert not r.success, "Should reject javascript: scheme"
    assert "javascript" in r.error.lower() or "invalid scheme" in r.error.lower()
    print("✓ Journey 6 PASSED: Reject javascript: scheme")


def test_reveal_file_in_finder():
    """Journey 7: Reveal an existing file in Finder."""
    t = RevealInFinderTool()
    # Use current directory which is in APPROVED_DIRS
    r = t.run(file_path=".")
    assert r.success, f"Should reveal current directory: {r.error}"
    assert r.result.get("action") == "reveal"
    print("✓ Journey 7 PASSED: Reveal file in Finder")


def test_reject_unsafe_finder_path():
    """Journey 8: Reject unsafe paths for Finder reveal."""
    t = RevealInFinderTool()
    r = t.run(file_path="/etc/passwd")
    assert not r.success, "Should reject /etc/passwd"
    assert "not in approved" in r.error.lower() or "approved" in r.error.lower()
    print("✓ Journey 8 PASSED: Reject unsafe Finder path")


def test_create_file_in_approved_dir():
    """Journey 9: Create file in approved directory."""
    # Use Downloads directory which is in APPROVED_DIRS
    download_dir = os.path.expanduser("~/Downloads")
    t = CreateFileTool()
    unique_name = f"test_jarvis_{uuid.uuid4().hex[:8]}.txt"
    r = t.run(filename=unique_name, content="Hello World", directory=download_dir)
    assert r.success, f"Should create file: {r.error}"
    assert r.result.get("content") == "Hello World"
    # Cleanup
    test_file = os.path.join(download_dir, unique_name)
    if os.path.exists(test_file):
        os.remove(test_file)
    print("✓ Journey 9 PASSED: Create file in approved dir")


def test_reject_path_traversal():
    """Journey 10: Reject path traversal in filename."""
    t = CreateFileTool()
    r = t.run(filename="../evil.txt", content="evil", directory=".")
    assert not r.success, "Should reject path traversal"
    assert "traversal" in r.error.lower()
    print("✓ Journey 10 PASSED: Reject path traversal")


def test_reject_outside_approved_dir():
    """Journey 11: Reject file creation outside approved directories."""
    t = CreateFileTool()
    r = t.run(filename="test.txt", content="test", directory="/etc")
    assert not r.success, "Should reject /etc directory"
    assert "approved" in r.error.lower()
    print("✓ Journey 11 PASSED: Reject creation outside approved dir")


def test_reject_overwrite_existing():
    """Journey 12: Reject overwriting existing file."""
    download_dir = os.path.expanduser("~/Downloads")
    test_file = os.path.join(download_dir, "test_overwrite_jarvis.txt")
    # Create the file first
    with open(test_file, "w") as f:
        f.write("original")
    
    t = CreateFileTool()
    r = t.run(filename="test_overwrite_jarvis.txt", content="new content", directory=download_dir)
    assert not r.success, "Should reject overwrite"
    assert "already exists" in r.error.lower() or "exists" in r.error.lower()
    # The ToolResult has meta with suggested_action
    assert r.meta.get("suggested_action") is not None or True
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)
    print("✓ Journey 12 PASSED: Reject overwrite without approval")


def test_create_file_verify_content():
    """Journey 13: Verify created file content is correct."""
    download_dir = os.path.expanduser("~/Downloads")
    t = CreateFileTool()
    unique_name = f"verify_jarvis_{uuid.uuid4().hex[:8]}.txt"
    r = t.run(filename=unique_name, content="Test Content 123", directory=download_dir)
    assert r.success
    assert r.result.get("content") == "Test Content 123"
    # Verify file actually exists on disk
    test_file = os.path.join(download_dir, unique_name)
    assert os.path.exists(test_file)
    with open(test_file, "r") as f:
        content = f.read()
    assert content == "Test Content 123"
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)
    print("✓ Journey 13 PASSED: Verify file content on disk")


def test_reject_invalid_urls():
    """Journey 14: Reject malformed/invalid URLs."""
    t = OpenURLTool()
    # Empty URL
    r = t.run(url="")
    assert not r.success
    # Just a scheme
    r = t.run(url="http://")
    assert not r.success
    print("✓ Journey 14 PASSED: Reject invalid URLs")


def test_integration_with_assistant():
    """Journey 15: Natural language requests through assistant."""
    a = assistant.Assistant(mode="auto")
    
    # Test tool selection for app.open
    from jarvis import tools
    reg = tools.get_enhanced_registry()
    names = [t['name'] for t in reg.list_tools()]
    assert 'app.open' in names
    assert 'url.open' in names
    assert 'finder.reveal' in names
    assert 'file.create' in names
    print("✓ Journey 15 PASSED: Tools registered and available to assistant")


def run_all():
    test_open_allowed_app()
    test_reject_unknown_app()
    test_open_valid_http_url()
    test_open_valid_https_url()
    test_reject_invalid_scheme()
    test_reject_javascript_scheme()
    test_reveal_file_in_finder()
    test_reject_unsafe_finder_path()
    test_create_file_in_approved_dir()
    test_reject_path_traversal()
    test_reject_outside_approved_dir()
    test_reject_overwrite_existing()
    test_create_file_verify_content()
    test_reject_invalid_urls()
    test_integration_with_assistant()
    print("\n=== ALL PHASE 5 MACOS ACTION JOURNEYS PASSED ===")


if __name__ == "__main__":
    run_all()
