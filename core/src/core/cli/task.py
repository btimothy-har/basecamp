"""CLI commands for task management."""

import sys

import rich_click as click

from core.exceptions import LauncherError
from core.task.operations import create_task, dispatch_task, list_tasks, register_task
from core.ui import console, err_console


def _handle_error(e: LauncherError) -> None:
    err_console.print(f"[red]Error:[/red] {e}")
    sys.exit(1)


@click.group()
def task() -> None:
    """Manage dispatch tasks."""


@task.command()
@click.option("--name", "-n", default=None, help="Task name suffix (auto-generated if omitted)")
@click.option("--model", "-m", default="sonnet", help="Model for the worker session (default: sonnet)")
@click.option("--dispatch", "do_dispatch", is_flag=True, help="Spawn terminal pane immediately after creation")
def create(name: str | None, model: str, do_dispatch: bool) -> None:  # noqa: FBT001
    """Create a dispatch task. Reads prompt from stdin.

    \b
    Example:
        basecamp task create --name fix-auth-bug --dispatch <<'PROMPT'
        Fix the authentication bug in the login flow.
        PROMPT
    """
    try:
        prompt: str | None = None
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip() or None

        entry = create_task(name=name, prompt=prompt, model=model, dispatch=do_dispatch)

        status = "dispatched" if do_dispatch else "staged"
        console.print(f"[bold green]Created[/bold green] task [cyan]{entry.name}[/cyan] ({status})")
        console.print(f"  [dim]Task dir:[/dim] {entry.task_dir}")
        if entry.worker_session_id:
            console.print(f"  [dim]Session:[/dim] {entry.worker_session_id}")
        elif do_dispatch:
            console.print("  [dim]Session:[/dim] (timed out)")
    except LauncherError as e:
        _handle_error(e)


@task.command("dispatch")
@click.option("--name", "-n", required=True, help="Name of the staged task to dispatch")
def dispatch_cmd(name: str) -> None:
    """Dispatch a previously staged task, or resume if already dispatched."""
    try:
        entry, resumed = dispatch_task(name=name)

        if resumed:
            console.print(f"[bold blue]Resumed[/bold blue] task [cyan]{entry.name}[/cyan]")
        else:
            console.print(f"[bold green]Dispatched[/bold green] task [cyan]{entry.name}[/cyan]")
        console.print(f"  [dim]Task dir:[/dim] {entry.task_dir}")
        if entry.worker_session_id:
            console.print(f"  [dim]Session:[/dim] {entry.worker_session_id}")
        elif not resumed:
            console.print("  [dim]Session:[/dim] (timed out)")
    except LauncherError as e:
        _handle_error(e)


@task.command("register", hidden=True)
@click.argument("session_id")
def register_cmd(session_id: str) -> None:
    """Register a worker's session ID (called by SessionStart hook)."""
    try:
        register_task(session_id=session_id)
    except LauncherError as e:
        _handle_error(e)


@task.command("list")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show tasks from all sessions, not just current")
def list_cmd(show_all: bool) -> None:  # noqa: FBT001
    """List tasks for the current project."""
    try:
        entries = list_tasks(show_all=show_all)

        if not entries:
            console.print("[dim]No tasks found.[/dim]")
            return

        for entry in entries:
            dispatched = entry.worker_session_id is not None
            status_color = "green" if dispatched else "yellow"
            status_label = "dispatched" if dispatched else "staged"
            worker = entry.worker_session_id or "[dim]—[/dim]"
            console.print(
                f"  [cyan]{entry.name}[/cyan]  "
                f"[{status_color}]{status_label}[/{status_color}]  "
                f"[dim]model:[/dim] {entry.model}  "
                f"[dim]worker:[/dim] {worker}"
            )
    except LauncherError as e:
        _handle_error(e)
