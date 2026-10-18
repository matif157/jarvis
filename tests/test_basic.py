"""Basic tests for Jarvis"""

import re
import tempfile

from jarvis import __version__
from jarvis.core import JarvisCore, Note


def test_version():
    assert re.match(r"^\d+\.\d+\.\d+$", __version__)


def test_note_creation():
    note = Note(id="test_1", content="Test note")
    assert note.content == "Test note"
    assert note.id == "test_1"


def test_core_add_note():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = JarvisCore(data_dir=tmpdir)
        note = core.add_note("Hello world", tags=["test"])
        assert note.content == "Hello world"
        assert "test" in note.tags
