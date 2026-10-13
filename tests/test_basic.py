"""Basic tests for Jarvis"""

from jarvis import __version__
from jarvis.core import JarvisCore, Note
import tempfile
import os


def test_version():
    assert __version__ == "0.2.0"


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
