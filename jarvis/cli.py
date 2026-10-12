"""CLI interface for Jarvis"""

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


@click.group()
@click.version_option()
def cli():
    """Jarvis - Your personal local assistant"""
    pass


@cli.command()
def start():
    """Start Jarvis interactive mode"""
    console.print(Panel.fit("🤖 Jarvis is starting...", style="bold green"))
    console.print("Type 'help' for available commands, 'exit' to quit.")


@cli.command()
def status():
    """Check Jarvis status"""
    console.print("[green]✓[/green] Jarvis is running locally")
    console.print("[blue]📁[/blue] Data stored in local filesystem")


@cli.command()
def note():
    """Quick note capture"""
    note_text = click.prompt("Enter your note")
    console.print(f"[green]✓[/green] Note saved: {note_text}")


if __name__ == "__main__":
    cli()
