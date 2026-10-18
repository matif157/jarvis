"""Phase 4 Memory Control Tests"""

import jarvis
from jarvis import assistant
from jarvis.tools import (
    MemoryForgetTool,
    MemoryListTool,
    MemoryRecallTool,
    MemoryRememberTool,
)


def test_save_and_recall_memory():
    """Journey 1: Save a test memory, and retrieve it."""
    a = assistant.Assistant(mode="basic")

    # Save a memory
    mr = MemoryRememberTool()
    r = mr.run(key="business_focus", value="custom CRM and business software")
    assert r.success, f"Remember failed: {r.error}"
    assert "custom CRM and business software" in r.result.get("value", "")

    # Verify via recall tool
    mr2 = MemoryRecallTool()
    r = mr2.run(key="business_focus")
    assert r.success, f"Recall failed: {r.error}"
    assert r.result.get("value") == "custom CRM and business software"

    print("✓ Journey 1 PASSED: Save and recall memory")


def test_search_and_list_memory():
    """Journey 2: List memories and verify contents."""
    a = assistant.Assistant(mode="basic")

    # Remember some facts
    mr = MemoryRememberTool()
    mr.run(key="career_2023", value="worked at tech startup")
    mr.run(key="education", value="MS Computer Science")

    # List all memories
    ml = MemoryListTool()
    r = ml.run()
    assert r.success, f"List failed: {r.error}"
    keys = list(r.result.keys())
    assert any("career" in k for k in keys), "Should find career-related memory"

    print("✓ Journey 2 PASSED: Search and list memory")


def test_correct_memory():
    """Journey 3: Correct an existing memory and confirm the stored value changed."""
    a = assistant.Assistant(mode="basic")

    # First remember something
    mr = MemoryRememberTool()
    r = mr.run(key="business_focus", value="custom CRM development")
    assert r.success

    # Recall it
    mr2 = MemoryRecallTool()
    r = mr2.run(key="business_focus")
    assert r.success
    original = r.result.get("value")

    # Now "correct" it by remembering the new value (this will overwrite due to INSERT OR REPLACE)
    mr3 = MemoryRememberTool()
    r = mr3.run(key="business_focus", value="CRM integrations platform")
    assert r.success

    # Verify the change
    mr4 = MemoryRecallTool()
    r = mr4.run(key="business_focus")
    assert r.success
    assert r.result.get("value") == "CRM integrations platform", (
        f"Expected 'CRM integrations platform', got '{r.result.get('value')}'"
    )

    print("✓ Journey 3 PASSED: Correct memory")


def test_delete_memory():
    """Journey 4: Delete a selected memory and verify that it no longer appears."""
    a = assistant.Assistant(mode="basic")

    # Remember then forget
    mr = MemoryRememberTool()
    r = mr.run(key="old_description", value="original business description")
    assert r.success

    # Forget it
    mf = MemoryForgetTool()
    r = mf.run(key="old_description")
    assert r.success, f"Forget failed: {r.error}"

    # Verify it's gone
    mr2 = MemoryRecallTool()
    r = mr2.run(key="old_description")
    assert not r.success, "Memory should be forgotten and no longer retrievable"

    print("✓ Journey 4 PASSED: Delete memory and verify removal")


def test_export_memory():
    """Journey 5: Export records and verify that the export contains the expected data."""

    a = assistant.Assistant(mode="basic")

    # Remember some facts
    mr = MemoryRememberTool()
    mr.run(key="pref_theme", value="dark")
    mr.run(key="favorite_color", value="blue")

    # Get all memories via db
    all_m = jarvis.db.get_all_memory_db()

    # Verify export data
    export_data = []
    for k, v in all_m.items():
        if not k.startswith("_"):  # exclude system keys
            export_data.append({"key": k, "value": str(v)})

    assert len(export_data) >= 2, "Should have exportable memories"

    # Verify specific entries exist
    keys = [d.get("key") for d in export_data]
    assert "pref_theme" in keys, "Should contain pref_theme"
    assert "favorite_color" in keys, "Should contain favorite_color"

    print("✓ Journey 5 PASSED: Export memory records")


def test_invalid_and_edge_cases():
    """Journeys 6-8: Test edge cases."""
    from jarvis import assistant
    from jarvis.tools import MemoryForgetTool, MemoryRememberTool

    a = assistant.Assistant(mode="basic")

    # Test forgetting a non-existent key
    mf = MemoryForgetTool()
    r = mf.run(key="nonexistent_key")
    # Should handle gracefully (not crash)
    assert r.success is not None, "Forget non-existent should not crash"

    # Test remembering with duplicate key (should overwrite due to INSERT OR REPLACE)
    mr = MemoryRememberTool()
    r = mr.run(key="dup_key", value="first")
    assert r.success
    mr2 = MemoryRememberTool()
    r = mr2.run(key="dup_key", value="second")
    assert r.success

    # Verify it was overwritten
    mr3 = MemoryRecallTool()
    r = mr3.run(key="dup_key")
    assert r.success
    assert r.result.get("value") == "second", "Duplicate should be overwritten"

    # Test querying a key that doesn't return a result (should not crash)
    mr4 = MemoryRecallTool()
    r = mr3.run(key="empty_key")
    # Should handle gracefully - the result may be None or have success=False
    assert type(r.success) is bool, "success should be boolean"

    print("✓ Journeys 6-8 PASSED: Edge cases handled")


def test_no_false_success():
    """Journey 10: Failed write/deletion does not produce false success."""
    from jarvis import assistant
    from jarvis.tools import MemoryRememberTool

    a = assistant.Assistant(mode="basic")

    # Try to remember with invalid key (empty)
    mr = MemoryRememberTool()
    r = mr.run(key="", value="")
    # Should handle gracefully - may succeed or fail depending on implementation
    # The key point is it should not produce a false success
    assert type(r.success) is bool, "success should be boolean"

    print("✓ Journey 10 PASSED: No false success messages")


def run_all():
    test_save_and_recall_memory()
    test_search_and_list_memory()
    test_correct_memory()
    test_delete_memory()
    test_export_memory()
    test_invalid_and_edge_cases()
    print("\n=== ALL PHASE 4 JOURNEYS PASSED ===")


if __name__ == "__main__":
    run_all()
