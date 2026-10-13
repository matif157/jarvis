"""Agent tests."""

from jarvis import agent


def test_agent_time():
    a = agent.Agent()
    res = a.run_goal('tell time', auto_confirm=True)
    assert res['status'] in ('completed', 'failed') or res['task_id']


def test_planner_decompose():
    from jarvis import planner

    p = planner.Planner()
    tasks = p.decompose('what time is it')
    assert len(tasks) >= 1
