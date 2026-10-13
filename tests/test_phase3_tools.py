"""Phase 3 specific tool tests."""

from jarvis import tools, tools_fs


def test_fs_tools_registered():
    reg = tools.get_enhanced_registry()
    names = [t['name'] for t in reg.list_tools()]
    assert 'fs.list' in names
    assert 'fs.read' in names


def test_fs_list_current():
    reg = tools.get_enhanced_registry()
    res = reg.execute('fs.list', directory='.')
    assert res.success
    assert isinstance(res.result, list)


def test_fs_read_self():
    reg = tools.get_enhanced_registry()
    # read a small file
    res = reg.execute('fs.read', path='README.md', max_chars=100)
    assert res.success
