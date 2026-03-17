"""Reflect command — launch a Claude session for reflective journaling."""

import datetime
import os
import shlex
import shutil
from importlib import resources
from io import StringIO

from rich.console import Console

from core.constants import CLAUDE_COMMAND, OBSERVER_CONFIG, SCRIPT_DIR, USER_PROMPTS_DIR
from core.logseq import resolve_graph_path
from core.utils import is_observer_configured


def _load_reflect_prompt() -> str:
    """Load the reflect prompt, checking user dir before package default."""
    user_path = USER_PROMPTS_DIR / "reflect.md"
    if user_path.exists():
        return user_path.read_text()
    return resources.files("core.prompts._system_prompts").joinpath("reflect.md").read_text()


def _build_startup_text(graph_path: str, today: str) -> str:
    """Render the reflect startup banner."""
    buf = StringIO()
    c = Console(file=buf, force_terminal=True)
    c.print("\n[bold green]Starting Claude[/bold green] in [cyan]reflect[/cyan] mode")
    c.print(f"  [dim]Graph:[/dim] {graph_path}")
    c.print(f"  [dim]Date:[/dim] {today}")
    c.print()
    return buf.getvalue()


def execute_reflect() -> None:
    """Launch a Claude session for reflective journaling against the Logseq graph.

    Raises:
        LogseqNotConfiguredError: If logseq_graph is not set.
        LogseqGraphNotFoundError: If the graph directory doesn't exist.
    """
    graph_path = resolve_graph_path()
    today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()

    # Assemble prompt: date context + reflect prompt
    reflect_content = _load_reflect_prompt()
    prompt_content = f"Today's date: {today}\n\n{reflect_content}"

    # Build claude command
    cmd: list[str] = [CLAUDE_COMMAND, "--system-prompt", prompt_content]

    # Load observer plugin for MCP access (cross-project session search)
    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        cmd.extend(["--plugin-dir", str(observer_plugin_dir)])

    os.chdir(graph_path)

    startup_text = _build_startup_text(str(graph_path), today)

    # Wrap in tmux if not already inside a session
    if not os.environ.get("TMUX") and shutil.which("tmux"):
        tmux_cmd = ["tmux", "new-session", "-A", "-s", "bc-reflect"]
        inner = f"printf %s {shlex.quote(startup_text)} && exec {shlex.join(cmd)}"
        tmux_cmd.extend(["sh", "-c", inner])
        os.execvp("tmux", tmux_cmd)
    else:
        print(startup_text, end="")
        os.execvp(CLAUDE_COMMAND, cmd)
