"""Phase 13 Resumable Workflows Tests (offline; temp store, no network)."""

import tempfile
from pathlib import Path

from jarvis.permissions import PermissionManager
from jarvis.workflows import (
    Workflow,
    WorkflowEngine,
    WorkflowStep,
    WorkflowStore,
    get_workflow_tools,
)


def make_engine():
    d = tempfile.mkdtemp(prefix="wf_test_")
    return WorkflowEngine(store=WorkflowStore(path=Path(d)))


# 1
def test_step_dataclass_defaults():
    s = WorkflowStep(id="a", tool="echo")
    assert s.status == "pending"
    assert s.args == {}
    assert s.attempts == 0
    assert s.max_retries == 0
    assert s.optional is False
    print("✓ Test 1 PASSED: WorkflowStep defaults")


# 2
def test_workflow_dataclass_defaults():
    wf = Workflow(id="wf_x", name="demo")
    assert wf.status == "pending"
    assert wf.steps == []
    assert wf.created_at and wf.updated_at
    assert wf.next_step() is None
    print("✓ Test 2 PASSED: Workflow defaults")


# 3
def test_store_save_and_load_roundtrip():
    d = tempfile.mkdtemp(prefix="wf_test_")
    store = WorkflowStore(path=Path(d))
    wf = Workflow(id="wf_1", name="roundtrip", steps=[WorkflowStep(id="s1", tool="echo", args={"text": "hi"})])
    store.save(wf)
    loaded = store.load("wf_1")
    assert loaded is not None
    assert loaded.name == "roundtrip"
    assert len(loaded.steps) == 1
    assert loaded.steps[0].tool == "echo"
    print("✓ Test 3 PASSED: WorkflowStore save/load roundtrip")


# 4
def test_store_list_and_filters():
    d = tempfile.mkdtemp(prefix="wf_test_")
    store = WorkflowStore(path=Path(d))
    a = Workflow(id="wf_a", name="a", tags=["x"])
    b = Workflow(id="wf_b", name="b", status="completed")
    store.save(a)
    store.save(b)
    assert len(store.list()) == 2
    assert [w.id for w in store.list(status="completed")] == ["wf_b"]
    assert [w.id for w in store.list(tag="x")] == ["wf_a"]
    print("✓ Test 4 PASSED: WorkflowStore list + status/tag filters")


# 5
def test_store_delete():
    d = tempfile.mkdtemp(prefix="wf_test_")
    store = WorkflowStore(path=Path(d))
    store.save(Workflow(id="wf_del", name="d"))
    assert store.delete("wf_del") is True
    assert store.load("wf_del") is None
    assert store.delete("wf_del") is False
    print("✓ Test 5 PASSED: WorkflowStore delete")


# 6
def test_engine_create_builds_steps():
    eng = make_engine()
    wf = eng.create(name="demo", steps=[{"tool": "echo", "args": {"text": "a"}}, {"tool": "time.now"}])
    assert wf.id.startswith("wf_")
    assert [s.id for s in wf.steps] == ["step1", "step2"]
    assert eng.get(wf.id).name == "demo"
    print("✓ Test 6 PASSED: engine.create builds steps with ids")


# 7
def test_engine_create_requires_name():
    eng = make_engine()
    try:
        eng.create(name="", steps=[{"tool": "echo"}])
        assert False, "expected ValueError"
    except ValueError:
        pass
    print("✓ Test 7 PASSED: engine.create requires a name")


# 8
def test_engine_start_completes_simple_workflow():
    eng = make_engine()
    wf = eng.create(name="simple", steps=[{"id": "a", "tool": "echo", "args": {"text": "x"}}])
    done = eng.start(wf.id)
    assert done.status == "completed"
    assert done.steps[0].status == "completed"
    assert done.steps[0].result == "x"
    print("✓ Test 8 PASSED: engine.start completes a simple workflow")


# 9
def test_state_survives_restart():
    d = tempfile.mkdtemp(prefix="wf_test_")
    eng = WorkflowEngine(store=WorkflowStore(path=Path(d)))
    wf = eng.create(name="persist", steps=[{"id": "a", "tool": "echo", "args": {"text": "x"}}])
    eng.start(wf.id)
    # simulate process restart with a fresh engine/store over the same dir
    eng2 = WorkflowEngine(store=WorkflowStore(path=Path(d)))
    reloaded = eng2.get(wf.id)
    assert reloaded is not None and reloaded.status == "completed"
    print("✓ Test 9 PASSED: workflow state survives an engine restart")


# 10
def test_interpolation_from_previous_step_result():
    eng = make_engine()
    wf = eng.create(
        name="interp",
        steps=[
            {"id": "a", "tool": "echo", "args": {"text": "hello"}},
            {"id": "b", "tool": "echo", "args": {"text": "${steps.a.result}"}},
        ],
    )
    done = eng.start(wf.id)
    assert done.status == "completed"
    assert done.steps[1].result == "hello"
    print("✓ Test 10 PASSED: ${steps.<id>.result} interpolation")


# 11
def test_interpolation_goal_and_context():
    eng = make_engine()
    wf = eng.create(
        name="ctx",
        goal="my goal",
        context={"who": "world"},
        steps=[
            {"id": "a", "tool": "echo", "args": {"text": "${goal}"}},
            {"id": "b", "tool": "echo", "args": {"text": "${context.who}"}},
        ],
    )
    done = eng.start(wf.id)
    assert done.steps[0].result == "my goal"
    assert done.steps[1].result == "world"
    print("✓ Test 11 PASSED: ${goal} and ${context.key} interpolation")


# 12
def test_gated_step_blocks_start():
    eng = make_engine()
    wf = eng.create(name="gated", steps=[{"id": "g", "tool": "voice.listen", "args": {}}])
    blocked = eng.start(wf.id)
    assert blocked.status == "blocked"
    assert blocked.steps[0].status == "blocked"
    print("✓ Test 12 PASSED: gated step blocks a workflow start")


# 13
def test_resume_without_confirm_stays_blocked():
    eng = make_engine()
    wf = eng.create(name="gated", steps=[{"id": "g", "tool": "voice.listen", "args": {}}])
    eng.start(wf.id)
    still = eng.resume(wf.id, confirm=False)
    assert still.status == "blocked"
    print("✓ Test 13 PASSED: resume without confirm stays blocked")


# 14
def test_resume_with_confirm_proceeds_honestly():
    eng = make_engine()
    wf = eng.create(name="gated", steps=[{"id": "g", "tool": "voice.listen", "args": {}}])
    eng.start(wf.id)
    resumed = eng.resume(wf.id, confirm=True)
    # No STT backend installed -> the gated step runs and fails honestly.
    assert resumed.status == "failed"
    assert resumed.steps[0].status == "failed"
    assert resumed.steps[0].error
    print("✓ Test 14 PASSED: resume with confirm runs gated step (honest failure offline)")


# 15
def test_resume_skips_completed_steps():
    eng = make_engine()
    wf = eng.create(
        name="skip",
        steps=[
            {"id": "a", "tool": "echo", "args": {"text": "first"}},
            {"id": "b", "tool": "voice.listen", "args": {}},
        ],
    )
    eng.start(wf.id)
    reloaded = eng.get(wf.id)
    assert reloaded.steps[0].status == "completed"
    assert reloaded.steps[1].status == "blocked"
    resumed = eng.resume(wf.id, confirm=True)
    assert resumed.steps[0].status == "completed"  # not re-run
    assert resumed.steps[0].attempts == 1
    print("✓ Test 15 PASSED: resume skips already-completed steps")


# 16
def test_optional_step_failure_is_skipped():
    eng = make_engine()
    wf = eng.create(
        name="opt",
        steps=[
            {"id": "bad", "tool": "no.such.tool", "optional": True},
            {"id": "ok", "tool": "echo", "args": {"text": "done"}},
        ],
    )
    done = eng.start(wf.id)
    assert done.status == "completed"
    assert done.steps[0].status == "skipped"
    assert done.steps[1].status == "completed"
    print("✓ Test 16 PASSED: optional failed step is skipped, workflow continues")


# 17
def test_continue_on_error_step():
    eng = make_engine()
    wf = eng.create(
        name="cont",
        steps=[
            {"id": "bad", "tool": "no.such.tool", "continue_on_error": True},
            {"id": "ok", "tool": "echo", "args": {"text": "go"}},
        ],
    )
    done = eng.start(wf.id)
    assert done.status == "completed"
    assert done.steps[0].status == "failed"
    assert done.steps[1].status == "completed"
    print("✓ Test 17 PASSED: continue_on_error moves past a failed step")


# 18
def test_required_step_failure_fails_workflow():
    eng = make_engine()
    wf = eng.create(name="fail", steps=[{"id": "bad", "tool": "no.such.tool"}])
    done = eng.start(wf.id)
    assert done.status == "failed"
    assert done.error
    print("✓ Test 18 PASSED: required step failure fails the workflow")


# 19
def test_retries_attempts_recorded():
    eng = make_engine()
    wf = eng.create(name="retry", steps=[{"id": "bad", "tool": "no.such.tool", "max_retries": 2}])
    done = eng.start(wf.id)
    assert done.steps[0].attempts == 3  # 1 initial + 2 retries
    print("✓ Test 19 PASSED: max_retries records attempts (1 + retries)")


# 20
def test_pause_and_cancel():
    eng = make_engine()
    wf = eng.create(name="life", steps=[{"id": "a", "tool": "echo", "args": {"text": "x"}}])
    paused = eng.pause(wf.id)
    assert paused.status == "paused"
    resumed = eng.resume(wf.id)
    assert resumed.status == "completed"

    wf2 = eng.create(name="life2", steps=[{"id": "a", "tool": "echo", "args": {"text": "x"}}])
    cancelled = eng.cancel(wf2.id)
    assert cancelled.status == "cancelled"
    try:
        eng.resume(wf2.id)
        assert False, "expected ValueError on resume of cancelled workflow"
    except ValueError:
        pass
    print("✓ Test 20 PASSED: pause/resume and cancel are terminal-aware")


# 21
def test_unknown_workflow_raises():
    eng = make_engine()
    assert eng.get("wf_missing") is None
    for fn in (eng.start, eng.resume, eng.pause, eng.cancel):
        try:
            fn("wf_missing")
            assert False, f"{fn.__name__} should raise"
        except ValueError:
            pass
    print("✓ Test 21 PASSED: unknown workflow ids raise ValueError")


# 22
def test_from_goal_uses_planner():
    eng = make_engine()
    wf = eng.from_goal("what time is it", name="planned")
    assert wf.name == "planned"
    assert "planned" in wf.tags
    assert any(s.tool == "time.now" for s in wf.steps)
    print("✓ Test 22 PASSED: from_goal builds a planned workflow")


# 23
def test_registry_has_all_workflow_tools():
    from jarvis.tools import get_enhanced_registry

    names = {t["name"] for t in get_enhanced_registry().list_tools()}
    expected = {
        "workflow.create",
        "workflow.from_goal",
        "workflow.list",
        "workflow.get",
        "workflow.start",
        "workflow.resume",
        "workflow.pause",
        "workflow.cancel",
        "workflow.delete",
    }
    assert expected.issubset(names)
    assert len(get_workflow_tools()) == 9
    print("✓ Test 23 PASSED: all 9 workflow tools registered")


# 24
def test_tool_permissions_and_gating():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    by_name = {t.name: t for t in get_workflow_tools()}
    assert by_name["workflow.resume"].permissions == ["workflow.run"]
    assert by_name["workflow.start"].permissions == ["workflow.write"]
    assert by_name["workflow.get"].permissions == ["workflow.read"]

    pm = PermissionManager()
    assert pm.is_allowed("workflow.read") and pm.is_allowed("workflow.write")
    assert pm.needs_confirmation("workflow.run") is True
    assert pm.needs_confirmation("workflow.write") is False

    # resume without confirm is gated at the registry level
    res = reg.execute("workflow.resume", workflow_id="wf_none")
    assert res.success is False
    assert res.meta.get("needs_confirmation") is True
    print("✓ Test 24 PASSED: workflow permission model + registry gating")


# 25
def test_registry_tool_roundtrip():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    created = reg.execute("workflow.create", workflow_name="reg", steps=[{"id": "a", "tool": "echo", "args": {"text": "hi"}}])
    assert created.success, created.error
    wid = created.result["id"]
    try:
        started = reg.execute("workflow.start", workflow_id=wid)
        assert started.success and started.result["status"] == "completed"
        got = reg.execute("workflow.get", workflow_id=wid)
        assert got.success and len(got.result["steps"]) == 1
        listed = reg.execute("workflow.list")
        assert listed.success and listed.result["count"] >= 1
        missing = reg.execute("workflow.get", workflow_id="wf_missing")
        assert missing.success is False and "not found" in missing.error
    finally:
        reg.execute("workflow.delete", workflow_id=wid)
    print("✓ Test 25 PASSED: workflow tools roundtrip through the registry")


# 26
def test_tool_validation_errors():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    assert reg.execute("workflow.create", workflow_name="x").success is False
    assert reg.execute("workflow.create", steps=[{"tool": "echo"}]).success is False
    assert reg.execute("workflow.get").success is False
    assert reg.execute("workflow.start").success is False
    print("✓ Test 26 PASSED: workflow tools validate required arguments")


# 27
def test_summary_shape():
    eng = make_engine()
    wf = eng.create(name="sum", steps=[{"tool": "echo", "args": {"text": "x"}}, {"tool": "time.now"}])
    s = wf.summary()
    for key in ("id", "name", "status", "steps", "step_status", "created_at"):
        assert key in s
    assert s["steps"] == 2
    print("✓ Test 27 PASSED: workflow summary exposes expected fields")
