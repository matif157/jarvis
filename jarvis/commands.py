"""Command registry for Jarvis"""

from typing import Dict, Callable, List
from rich.console import Console

console = Console()


class CommandRegistry:
    """Registry for Jarvis commands"""

    def __init__(self):
        self.commands: Dict[str, Callable] = {}
        self._register_default()

    def _register_default(self):
        self.register("help", self._help)
        self.register("clear", self._clear)
        self.register("version", self._version)
        self.register("quit", self._quit)
        self.register("exit", self._quit)

    def register(self, name: str, func: Callable):
        self.commands[name] = func

    def get(self, name: str) -> Callable:
        return self.commands.get(name.lower())

    def list_commands(self) -> List[str]:
        return sorted(self.commands.keys())

    def _help(self):
        console.print("[bold]Available commands:[/bold]")
        for cmd in self.list_commands():
            console.print(f"  • {cmd}")
        console.print("\nAlso try: note, task, memory, weather, time, date")

    def _clear(self):
        console.clear()

    def _version(self):
        from . import __version__
        console.print(f"Jarvis v{__version__}")

    def _quit(self):
        from .assistant import Assistant
        console.print("Goodbye!")
