"""Reflect command — launch a Claude session for reflective journaling."""

import datetime
import os
import shlex
import shutil
from importlib import resources
from io import StringIO
from pathlib import Path

from rich.console import Console

from core.constants import CLAUDE_COMMAND, OBSERVER_CONFIG, SCRATCH_BASE, SCRIPT_DIR, USER_PROMPTS_DIR
from core.git import generate_git_status, get_remote_url, is_git_repo
from core.logseq import resolve_graph_path
from core.prompts.system import _load_environment_prompt, generate_env_block
from core.utils import is_observer_configured

REFLECT_SCRATCH_NAME = "reflect"

USER_PROMPT = """\
Review my work from today. Use the observer MCP tools to find all sessions:

1. Search transcripts for today's date to discover what I worked on
2. Get summaries for each session to understand the context
3. Search artifacts for key decisions, constraints, and knowledge

Then:
- Summarize what you found, grouped by logical threads of work (not by session or repo)
- Propose journal entries for the significant items
- Let me curate — accept, edit, reject, add project tags
- Write approved entries to today's journal file\
"""


def _load_reflect_prompt() -> str:
    """Load the reflect system prompt, checking user dir before package default."""
    user_path = USER_PROMPTS_DIR / "reflect.md"
    if user_path.exists():
        return user_path.read_text()
    return resources.files("core.prompts._system_prompts").joinpath("reflect.md").read_text()


def _assemble_system_prompt(graph_path: Path) -> str:
    """Assemble the reflect system prompt: env block + environment.md + reflect.md."""
    primary = graph_path
    repo = is_git_repo(primary)
    remote_url = get_remote_url(primary) if repo else None

    env_block = generate_env_block(primary, [], is_repo=repo, remote_url=remote_url, scratch_name=REFLECT_SCRATCH_NAME)
    environment_content, _ = _load_environment_prompt()
    git_status = generate_git_status(primary) if repo else None

    runtime_parts = [env_block, environment_content.strip()]
    if git_status:
        runtime_parts.append(git_status)

    reflect_content = _load_reflect_prompt()

    return "\n\n".join(["\n\n".join(runtime_parts), reflect_content.strip()])


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

    system_prompt = _assemble_system_prompt(graph_path)

    # Build claude command: system prompt + initial user prompt.
    # The -- separator ensures the prompt isn't misinterpreted as a flag.
    cmd: list[str] = [CLAUDE_COMMAND, "--system-prompt", system_prompt, "--", USER_PROMPT]

    # Load observer plugin for MCP access (cross-project session search)
    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        cmd.extend(["--plugin-dir", str(observer_plugin_dir)])

    os.chdir(graph_path)

    # Reflect mode: cross-project search, skip session ingestion
    os.environ["BASECAMP_REFLECT"] = "1"

    today = datetime.datetime.now().astimezone().date().isoformat()
    startup_text = _build_startup_text(str(graph_path), today)

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
