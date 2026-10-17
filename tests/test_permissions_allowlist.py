"""Permission allowlist enforcement tests (Phase 16 follow-up).

Verifies that `PermissionManager.is_allowed` actually enforces the allowlist
patterns when a resource is supplied, while remaining backward compatible for
scope-only callers (used by the tool registry for confirmation gating).
"""

import os

from jarvis.permissions import DEFAULT_ALLOWLIST, PermissionManager, _matches
from jarvis.tools import get_enhanced_registry


# 1
def test_default_allowlist_covers_all_scopes():
    for scope in (
        "email.connect",
        "email.read",
        "drive.access",
        "drive.read",
        "resume.parse",
        "resume.read",
        "resume.write",
        "career.read",
        "career.write",
        "web.research",
        "task.read",
        "task.write",
        "memory.read",
        "memory.write",
    ):
        assert scope in DEFAULT_ALLOWLIST, f"missing scope: {scope}"
    print("✓ Test 1 PASSED: default allowlist covers all tool scopes")


# 2
def test_pattern_matching_home_relative():
    home = os.path.expanduser("~")
    assert _matches(os.path.join(home, "Documents", "a.txt"), ["Documents/*"])
    assert _matches(os.path.join(home, "Downloads", "b.zip"), ["Downloads/*"])
    assert _matches(os.path.join(home, "anything", "c"), ["~/*"])
    assert not _matches("/etc/passwd", ["Documents/*", "Downloads/*", "~/*"])
    print("✓ Test 2 PASSED: home-relative glob patterns match correctly")


# 3
def test_is_allowed_enforces_resource_patterns():
    pm = PermissionManager()
    home = os.path.expanduser("~")
    assert pm.is_allowed("file.read", os.path.join(home, "Documents", "notes.md")) is True
    assert pm.is_allowed("file.read", os.path.join(home, "code", "x.py")) is True
    assert pm.is_allowed("file.read", "/etc/passwd") is False
    assert pm.is_allowed("file.read", "/etc") is False
    print("✓ Test 3 PASSED: is_allowed enforces file.read path patterns")


# 4
def test_scope_only_call_still_permissive():
    pm = PermissionManager()
    # No resource -> only deny/scope checks (backward compatible).
    assert pm.is_allowed("file.read") is True
    assert pm.is_allowed("file.delete") is True
    assert pm.is_allowed("web.search") is True
    print("✓ Test 4 PASSED: scope-only is_allowed stays backward compatible")


# 5
def test_empty_patterns_scope_denies_resource():
    pm = PermissionManager()
    # file.delete has an empty allowlist: with a concrete resource -> denied.
    assert pm.is_allowed("file.delete", "/tmp/x.txt") is False
    print("✓ Test 5 PASSED: empty allowlist denies a concrete resource")


# 6
def test_deny_overrides_allow():
    pm = PermissionManager()
    pm.deny.add("file.read")
    try:
        home = os.path.expanduser("~")
        assert pm.is_allowed("file.read", os.path.join(home, "Documents", "x")) is False
        assert pm.is_allowed("file.read") is False
    finally:
        pm.deny.discard("file.read")
    print("✓ Test 6 PASSED: deny overrides allowlist")


# 7
def test_unknown_scope_not_restricted():
    pm = PermissionManager()
    assert pm.is_allowed("totally.unknown.scope") is True
    assert pm.is_allowed("totally.unknown.scope", "/anywhere") is True
    print("✓ Test 7 PASSED: unknown scopes remain unrestricted (documented)")


# 8
def test_registry_enforces_resource_via_tool():
    reg = get_enhanced_registry()
    ok = reg.execute("fs.read", path="README.md", max_chars=80)
    assert ok.success, ok.error

    blocked = reg.execute("fs.read", path="/etc/passwd")
    assert not blocked.success
    assert "permission denied" in (blocked.error or "").lower()

    blocked_list = reg.execute("fs.list", directory="/etc")
    assert not blocked_list.success
    print("✓ Test 8 PASSED: registry enforces allowlist for resource-bearing tools")


# 9
def test_wildcard_scope_allows_any_resource():
    pm = PermissionManager()
    assert pm.is_allowed("web.search", "https://example.com") is True
    assert pm.is_allowed("app.open", "Safari") is True
    print("✓ Test 9 PASSED: wildcard scopes allow any resource")
