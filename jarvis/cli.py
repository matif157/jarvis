"""CLI interface for Jarvis."""

import asyncio

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__, atif_client, db, llm
from .config import PROVIDER_ORDER

console = Console()


@click.group()
@click.version_option(version=__version__)
def cli():
    """Jarvis - Your personal local assistant."""
    pass


@cli.command()
def start():
    """Start Jarvis interactive mode."""
    console.print(Panel.fit("Jarvis is starting...", style="bold green"))
    console.print("Type 'help' for available commands, 'exit' to quit.")


@cli.command()
def status():
    """Check Jarvis status and active answer mode."""
    console.print("[green]OK[/green] Jarvis is running locally")
    console.print("[blue]Data[/blue] stored in local SQLite database")
    console.print(f"[blue]AI providers[/blue] configured: {llm.has_provider()}")
    active = asyncio.run(llm.active_provider())
    console.print(f"[blue]Active provider[/blue] {active or '(none, using basics)'}")


@cli.command()
def note():
    """Quick note capture."""
    from .core import JarvisCore

    note_text = click.prompt("Enter your note")
    core = JarvisCore()
    core.add_note(note_text)
    console.print(f"[green]OK[/green] Note saved: {note_text}")


@cli.command()
def memory():
    """Memory management."""
    mem = db.get_all_memory_db()
    console.print(f"[blue]Memory[/blue] {len(mem)} entries stored locally")


@cli.command()
def task():
    """Quick task creation."""
    from .tasks import TaskManager

    title = click.prompt("Task title")
    tm = TaskManager()
    task = tm.add_task(title)
    console.print(f"[green]OK[/green] Task created: {task.title}")


@cli.command()
def weather():
    """Get weather info."""
    from .weather import Weather

    info = Weather().get_weather()
    console.print(
        f"[blue]Weather[/blue] in {info['location']}: {info['temperature']}C, {info['condition']}"
    )


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["auto", "basic", "llm", "atif"]),
    default="auto",
    help="Answer mode: auto tries Atif, then LLM, then basics.",
)
def chat(mode):
    """Start interactive chat with Jarvis."""
    from .assistant import Assistant

    Assistant(mode=mode).start()


# ------------------------------------------------------------- settings

@cli.group()
def settings():
    """View and edit settings, including API keys."""
    pass


@settings.command("list")
def settings_list():
    """List all settings (API keys masked)."""
    conn = db.connect()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    conn.close()
    if not rows:
        console.print("No settings stored yet.")
        return
    table = Table(title="Settings")
    table.add_column("Key")
    table.add_column("Value")
    for r in rows:
        key = r["key"]
        value = r["value"]
        if key.startswith("provider.") and key.endswith(".api_key"):
            value = llm.mask_key(value) if value else "(cleared)"
        table.add_row(key, value)
    console.print(table)


@settings.command("set")
@click.argument("key")
@click.argument("value")
def settings_set(key, value):
    """Set a setting, e.g. provider.groq.api_key sk-..."""
    db.set_setting(key, value)
    llm.invalidate_probe_cache()
    shown = llm.mask_key(value) if key.endswith(".api_key") else value
    console.print(f"[green]OK[/green] {key} = {shown}")


@settings.command("unset")
@click.argument("key")
def settings_unset(key):
    """Remove a setting (falls back to environment/default)."""
    db.delete_setting(key)
    llm.invalidate_probe_cache()
    console.print(f"[green]OK[/green] removed {key}")


# ------------------------------------------------------------ providers

@cli.group()
def providers():
    """Manage AI model providers and API keys."""
    pass


@providers.command("list")
def providers_list():
    """List providers with masked key hints."""
    table = Table(title="Providers")
    table.add_column("Name")
    table.add_column("Label")
    table.add_column("Enabled")
    table.add_column("Key")
    table.add_column("Model")
    for name in PROVIDER_ORDER:
        st = llm.provider_status(name)
        table.add_row(
            st["name"],
            st["label"],
            "yes" if st["enabled"] else "no",
            (st["key_hint"] or "(none)") if name != "ollama" else "(local)",
            st["model"],
        )
    console.print(table)


@providers.command("test")
@click.argument("name", required=False)
def providers_test(name):
    """Test one provider or all of them (live network probe)."""

    async def run():
        if name:
            result = await llm.test_provider(name)
            color = "green" if result["ready"] else "red"
            console.print(f"[{color}]{name}[/{color}]: {result.get('error') or 'ready'} ({result.get('latency_ms')} ms)")
        else:
            results = await asyncio.gather(*(llm.test_provider(n) for n in PROVIDER_ORDER))
            ready = 0
            for r in results:
                ok = r["ready"]
                ready += 1 if ok else 0
                color = "green" if ok else "red"
                detail = "ready" if ok else r.get("error")
                console.print(f"[{color}]{r['provider']}[/{color}]: {detail}")
            console.print(f"{ready} of {len(results)} providers ready.")

    asyncio.run(run())


@providers.command("key")
@click.argument("name")
@click.argument("api_key")
def providers_key(name, api_key):
    """Set a provider API key, e.g. providers key groq sk-..."""
    if name not in PROVIDER_ORDER:
        console.print(f"[red]Unknown provider: {name}[/red]")
        return
    db.set_setting(f"provider.{name}.api_key", api_key)
    llm.invalidate_probe_cache()
    console.print(f"[green]OK[/green] saved key for {name}: {llm.mask_key(api_key)}")


@providers.command("clear")
@click.argument("name")
def providers_clear(name):
    """Clear a provider's stored API key (disables it)."""
    if name not in PROVIDER_ORDER:
        console.print(f"[red]Unknown provider: {name}[/red]")
        return
    db.set_setting(f"provider.{name}.api_key", "")
    llm.invalidate_probe_cache()
    console.print(f"[green]OK[/green] cleared key for {name}")


@providers.command("enable")
@click.argument("name")
@click.argument("state", type=click.Choice(["on", "off"]))
def providers_enable(name, state):
    """Enable or disable a provider."""
    if name not in PROVIDER_ORDER:
        console.print(f"[red]Unknown provider: {name}[/red]")
        return
    db.set_setting(f"provider.{name}.enabled", "1" if state == "on" else "0")
    llm.invalidate_probe_cache()
    console.print(f"[green]OK[/green] {name} {'enabled' if state == 'on' else 'disabled'}")


# ------------------------------------------------------------- server

@cli.command()
@click.option("--host", default=None, help="Bind host (default 127.0.0.1)")
@click.option("--port", default=None, type=int, help="Bind port (default 8771)")
def serve(host, port):
    """Run Jarvis as an API server with a settings web UI."""
    import uvicorn

    from .config import HOST, PORT

    uvicorn.run(
        "jarvis.app:app",
        host=host or HOST,
        port=port or PORT,
        reload=False,
    )


# --------------------------------------------------------------- atif

@cli.group()
def atif():
    """Connect to an Atif Assistant instance."""
    pass


@atif.command("status")
def atif_status():
    """Check whether Atif Assistant is reachable."""

    async def run():
        result = await atif_client.health()
        if result.get("ok"):
            console.print(f"[green]OK[/green] Atif Assistant reachable at {result['url']}")
        else:
            console.print(f"[red]Unreachable[/red] at {result['url']}: {result.get('error')}")

    asyncio.run(run())


@atif.command("url")
@click.argument("url")
def atif_url(url):
    """Set the Atif Assistant URL, e.g. atif url http://localhost:8770"""
    db.set_setting("atif.url", url)
    console.print(f"[green]OK[/green] Atif URL set to {url}")


@atif.command("chat")
def atif_chat():
    """Chat through Atif Assistant."""
    from .assistant import Assistant

    Assistant(mode="atif").start()


@cli.command()
@click.option("--remove-json", is_flag=True, help="Delete JSON files after migrating.")
def migrate(remove_json):
    """Import legacy JSON data (notes/tasks/memory) into SQLite."""
    from .migrate import migrate as run_migration

    counts = run_migration(remove_json=remove_json)
    console.print(
        f"[green]OK[/green] migrated notes={counts['notes']} "
        f"tasks={counts['tasks']} memory={counts['memory']}"
    )


@cli.command()
def tools():
    """List available tools."""
    from .tools import get_default_registry

    reg = get_default_registry()
    for t in reg.list_tools():
        console.print(f"[cyan]{t['name']}[/cyan]: {t['description']}")


@cli.command()
@click.option("--confirm", is_flag=True, help="Auto-confirm confirmation-required actions")
def plan():
    """Simple planner/demo."""
    from .engine_tasks import TaskExecutor

    executor = TaskExecutor()
    task = executor.create_task("Demo task", steps=[{"tool": "time.now", "args": {}}])
    console.print(f"Created task {task.id}")
    executor.execute(task.id, confirm_all=confirm)


@cli.command()
@click.argument("task_id")
def resume(task_id):
    """Resume/inspect a stored task."""
    from .engine_tasks import TaskExecutor

    executor = TaskExecutor()
    task = executor.load(task_id)
    if not task:
        console.print(f"[red]Task not found[/red]: {task_id}")
        return
    console.print(json_dumps({"id": task.id, "goal": task.goal, "status": task.status, "steps": len(task.steps)}))


def json_dumps(obj):
    import json

    return json.dumps(obj, indent=2)


# ----------------------------------------------------------- workflows


@cli.group()
def workflow():
    """Create and run resumable workflows."""
    pass


@workflow.command("list")
@click.option("--status", default="", help="Filter by status")
def workflow_list(status):
    """List stored workflows."""
    from .workflows import WorkflowEngine

    items = WorkflowEngine().list(status=status or None)
    table = Table(title="Workflows")
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("status")
    table.add_column("steps")
    for wf in items:
        table.add_row(wf.id, wf.name, wf.status, str(len(wf.steps)))
    console.print(table)


@workflow.command("show")
@click.argument("workflow_id")
def workflow_show(workflow_id):
    """Show a workflow's full state."""
    from .workflows import WorkflowEngine

    wf = WorkflowEngine().get(workflow_id)
    if not wf:
        console.print(f"[red]Workflow not found[/red]: {workflow_id}")
        return
    console.print_json(json_dumps(__import__("dataclasses").asdict(wf)))


@workflow.command("create")
@click.argument("name")
@click.option("--step", "step_specs", multiple=True, help="TOOL[:k=v,...] step (repeatable)")
@click.option("--goal", default="", help="Goal description")
def workflow_create(name, step_specs, goal):
    """Create a workflow from one or more --step specs."""
    import json as _json

    from .workflows import WorkflowEngine

    steps = []
    for spec in step_specs:
        tool, _, args_s = spec.partition(":")
        args = {}
        if args_s:
            try:
                args = _json.loads(args_s)
            except Exception:
                for pair in args_s.split(","):
                    k, _, v = pair.partition("=")
                    if k:
                        args[k] = v
        steps.append({"tool": tool, "args": args})
    if not steps:
        console.print("[red]At least one --step is required[/red]")
        return
    wf = WorkflowEngine().create(name=name, steps=steps, goal=goal)
    console.print(f"Created workflow [cyan]{wf.id}[/cyan] ({len(wf.steps)} steps)")


@workflow.command("run")
@click.argument("workflow_id")
def workflow_run(workflow_id):
    """Start a workflow (gated steps will block)."""
    from .workflows import WorkflowEngine

    try:
        wf = WorkflowEngine().start(workflow_id, confirm=False)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(json_dumps(wf.summary()))


@workflow.command("resume")
@click.argument("workflow_id")
@click.option("--confirm", is_flag=True, help="Authorize confirmation-gated steps")
def workflow_resume(workflow_id, confirm):
    """Resume a paused/blocked/failed workflow."""
    from .workflows import WorkflowEngine

    try:
        wf = WorkflowEngine().resume(workflow_id, confirm=confirm)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(json_dumps(wf.summary()))


@workflow.command("cancel")
@click.argument("workflow_id")
def workflow_cancel(workflow_id):
    """Cancel a workflow."""
    from .workflows import WorkflowEngine

    try:
        wf = WorkflowEngine().cancel(workflow_id)
    except Exception as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(json_dumps(wf.summary()))


# --------------------------------------------------------------- iot


@cli.group()
def iot():
    """List and control optional smart devices."""
    pass


@iot.command("providers")
def iot_providers():
    """Show IoT provider availability."""
    from .iot import IoTManager

    for p in IoTManager().provider_status():
        state = "[green]available[/green]" if p["available"] else "[dim]unavailable[/dim]"
        console.print(f"{p['name']}: {state}")


@iot.command("list")
def iot_list():
    """List registered devices."""
    from .iot import IoTManager

    table = Table(title="Devices")
    table.add_column("id", style="cyan")
    table.add_column("name")
    table.add_column("provider")
    table.add_column("kind")
    table.add_column("state")
    for d in IoTManager().store.list():
        table.add_row(d.id, d.name, d.provider, d.kind, json_dumps(d.state))
    console.print(table)


@iot.command("add")
@click.argument("name")
@click.option("--provider", default="mock", help="mock|http|home_assistant")
@click.option("--kind", default="switch")
@click.option("--address", default="", help="URL (http) or entity_id (home_assistant)")
def iot_add(name, provider, kind, address):
    """Register a device."""
    from .iot import IoTManager

    try:
        d = IoTManager().add_device(name=name, provider=provider, kind=kind, address=address)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    console.print(f"Added [cyan]{d.id}[/cyan] ({d.provider})")


@iot.command("control")
@click.argument("device_id")
@click.argument("action")
@click.option("--value", default=None)
def iot_control(device_id, action, value):
    """Control a device (on/off/toggle/set/status)."""
    from .iot import IoTManager

    result = IoTManager().control(device_id, action, value)
    if not result.get("ok"):
        console.print(f"[red]{result.get('error')}[/red]")
        return
    console.print(json_dumps(result.get("state", {})))


@iot.command("remove")
@click.argument("device_id")
def iot_remove(device_id):
    """Remove a device."""
    from .iot import DeviceStore

    if DeviceStore().remove(device_id):
        console.print(f"Removed {device_id}")
    else:
        console.print(f"[red]Device not found[/red]: {device_id}")


if __name__ == "__main__":
    cli()
