"""Tool tests."""

from jarvis import tools


def test_registry_has_tools():
    reg = tools.get_enhanced_registry()
    names = [t['name'] for t in reg.list_tools()]
    assert 'time.now' in names
    assert 'fs.list' in names
    assert 'fs.read' in names


def test_time_tool():
    reg = tools.get_enhanced_registry()
    res = reg.execute('time.now')
    assert res.success
