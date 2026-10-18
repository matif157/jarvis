"""Phase 5 planning tests."""

from jarvis import agent, planner


def test_planner_general():
    p = planner.Planner()
    tasks = p.decompose('list files')
    assert len(tasks) >= 1


def test_agent_goal_flow():
    a = agent.Agent()
    res = a.run_goal('echo test', auto_confirm=True)
    assert 'status' in res
    assert res['status'] in ('completed', 'failed', 'pending', 'in_progress')
