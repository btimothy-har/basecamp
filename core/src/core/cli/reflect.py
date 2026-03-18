"""Reflect command — launch a Claude session for reflective journaling."""

import os
import shlex
import shutil
from io import StringIO
from pathlib import Path

from rich.console import Console

from core.constants import CLAUDE_COMMAND, OBSERVER_CONFIG, SCRATCH_BASE, SCRIPT_DIR
from core.git import is_git_repo
from core.logseq import resolve_graph_path, today
from core.prompts.logseq_prompts import load_system_prompt, load_user_prompt
from core.prompts.system import build_runtime_preamble
from core.utils import is_observer_configured

REFLECT_SCRATCH_NAME = "reflect"


def _assemble_system_prompt(graph_path: Path) -> str:
    """Assemble the reflect system prompt: runtime preamble + logseq system prompt."""
    repo = is_git_repo(graph_path)
    preamble, _ = build_runtime_preamble(graph_path, [], is_repo=repo, scratch_name=REFLECT_SCRATCH_NAME)
    logseq_content = load_system_prompt()
    return "\n\n".join([preamble, logseq_content.strip()])


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

    # Ensure scratch directory exists
    (SCRATCH_BASE / REFLECT_SCRATCH_NAME).mkdir(parents=True, exist_ok=True)

    target_date = today()
    system_prompt = _assemble_system_prompt(graph_path)
    user_prompt = load_user_prompt("reflect", date=target_date)

    # Build claude command — flags first, then -- separator + user prompt last
    # so the end-of-options marker doesn't swallow subsequent flags.
    cmd: list[str] = [CLAUDE_COMMAND, "--system-prompt", system_prompt]

    # Load observer plugin for MCP access (cross-project session search)
    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        cmd.extend(["--plugin-dir", str(observer_plugin_dir)])

    cmd.extend(["--", user_prompt])

    os.chdir(graph_path)

    # Reflect mode: cross-project search, skip session ingestion.
    # Set in os.environ so the non-tmux execvp path inherits it.
    # The tmux path also passes it explicitly via -e so the inner
    # shell inherits it even though tmux starts a fresh environment.
    os.environ["BASECAMP_REFLECT"] = "1"

    startup_text = _build_startup_text(str(graph_path), target_date.isoformat())

    # Wrap in tmux if not already inside a session.
    # Pass BASECAMP_REFLECT via -e so the observer plugin inherits it.
    if not os.environ.get("TMUX") and shutil.which("tmux"):
        tmux_cmd = ["tmux", "new-session", "-A", "-s", "bc-reflect", "-e", "BASECAMP_REFLECT=1"]
        inner = f"printf %s {shlex.quote(startup_text)} && exec {shlex.join(cmd)}"
        tmux_cmd.extend(["sh", "-c", inner])
        os.execvp("tmux", tmux_cmd)
    else:
        print(startup_text, end="")
        os.execvp(CLAUDE_COMMAND, cmd)
