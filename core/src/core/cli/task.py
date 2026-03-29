"""CLI commands for task management."""

import sys

import rich_click as click

from core.exceptions import LauncherError
from core.task.communication import ask_task, send_to_task
from core.task.operations import close_task, create_task, dispatch_task, list_tasks
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

        console.print(
            f"[bold green]Created[/bold green] task [cyan]{entry.name}[/cyan] ({entry.status.value})"
        )
        console.print(f"  [dim]Task dir:[/dim] {entry.task_dir}")
        console.print(f"  [dim]Session:[/dim] {entry.session_id}")
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
        console.print(f"  [dim]Session:[/dim] {entry.session_id}")
    except LauncherError as e:
        _handle_error(e)


@task.command("close", hidden=True)
def close_cmd() -> None:
    """Mark a worker task as closed (called by SessionEnd hook)."""
    try:
        close_task()
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
            status_color = {"staged": "yellow", "dispatched": "green", "closed": "dim"}[entry.status.value]
            console.print(
                f"  [cyan]{entry.name}[/cyan]  "
                f"[{status_color}]{entry.status.value}[/{status_color}]  "
                f"[dim]model:[/dim] {entry.model}  "
                f"[dim]session:[/dim] {entry.session_id}"
            )
    except LauncherError as e:
        _handle_error(e)


@task.command("ask")
@click.option("--name", "-n", required=True, help="Target task name or 'parent'")
@click.argument("message")
def ask_cmd(name: str, message: str) -> None:
    """Ask a question using a target session's context.

    Forks the target's conversation history and returns a response.
    The target session is not modified.

    Use --name parent from a worker to query the orchestrator.
    """
    try:
        response = ask_task(name=name, message=message)
        console.print(response)
    except LauncherError as e:
        _handle_error(e)


@task.command("send")
@click.option("--name", "-n", required=True, help="Target task name or 'parent'")
@click.option("--immediate", is_flag=True, help="Deliver at next tool call instead of next turn boundary")
@click.argument("message")
def send_cmd(name: str, immediate: bool, message: str) -> None:  # noqa: FBT001
    """Send a message to a task session's inbox.

    Message is delivered by a hook on the target session. By default,
    delivered at the next turn boundary (Stop event). Use --immediate
    for delivery at the next tool call.

    Use --name parent from a worker to message the orchestrator.
    """
    try:
        send_to_task(name=name, message=message, immediate=immediate)
        priority = "immediate" if immediate else "normal"
        console.print(f"[bold green]Sent[/bold green] ({priority}) → [cyan]{name}[/cyan]")
    except LauncherError as e:
        _handle_error(e)
