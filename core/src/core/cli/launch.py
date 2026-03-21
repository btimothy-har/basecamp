"""Launch implementation for basecamp CLI."""

import os
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from rich.console import Console

from core.config import Config, ProjectConfig, resolve_project, validate_dirs
from core.constants import (
    CLAUDE_COMMAND,
    OBSERVER_CONFIG,
    SCRATCH_BASE,
    SCRIPT_DIR,
    USER_ASSEMBLED_PROMPTS_DIR,
    USER_CONTEXT_DIR,
)
from core.exceptions import DirectoryNotFoundError, NoDirectoriesConfiguredError, NotAGitRepoError
from core.git import (
    WorktreeInfo,
    get_or_create_worktree,
    get_repo_name,
    is_git_repo,
)
from core.prompts import system as prompts
from core.terminal import resolve_launch_backend
from core.utils import is_observer_configured

DEFAULT_PATH_WORKING_STYLE = "engineering"


def _build_startup_text(
    project_name: str,
    primary_dir: Path,
    worktree_info: WorktreeInfo | None,
    *,
    worktree_created: bool,
    secondary_dirs: list[Path],
    working_style: str | None,
) -> str:
    """Render the startup banner to an ANSI-colored string.

    Uses a Rich Console writing to a buffer so the output can be displayed
    inside a tmux session (where the original stdout is replaced).
    """
    buf = StringIO()
    c = Console(file=buf, force_terminal=True)

    c.print(f"\n[bold green]Starting Claude[/bold green] with project [cyan]{project_name}[/cyan]")
    c.print(f"  [dim]Primary:[/dim] {primary_dir}")
    if worktree_info:
        status = "new" if worktree_created else "existing"
        c.print(f"  [dim]Worktree:[/dim] {worktree_info.name} ({status})")
        c.print(f"  [dim]Branch:[/dim] {worktree_info.branch}")
    if secondary_dirs:
        c.print("  [dim]Added dirs:[/dim]")
        for directory in secondary_dirs:
            c.print(f"    • {directory}")
    if working_style:
        c.print(f"  [dim]Working style:[/dim] {working_style}")
    c.print()
    return buf.getvalue()


def _ensure_scratch_dir(project_name: str) -> None:
    """Create the per-project scratch directory if it doesn't exist."""
    (SCRATCH_BASE / project_name).mkdir(parents=True, exist_ok=True)


def is_path_argument(value: str) -> bool:
    """Detect if a CLI argument looks like a filesystem path rather than a project name."""
    return value.startswith((".", "/", "~")) or "/" in value


def resolve_path_argument(value: str) -> Path:
    """Resolve a path argument to an absolute directory.

    Raises:
        DirectoryNotFoundError: If the path doesn't exist or isn't a directory.
    """
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise DirectoryNotFoundError([f"{value} ({path})"])
    if not path.is_dir():
        raise DirectoryNotFoundError([f"{value} ({path}) [not a directory]"])
    return path


def execute_launch(
    project_name: str,
    config: Config,
    *,
    resume: bool = False,
    label: str | None = None,
    resolved_path: Path | None = None,
) -> None:
    """Launch Claude Code with the specified project configuration.

    Args:
        project_name: The project to launch (display name).
        config: The loaded configuration.
        resume: Whether to resume a previous conversation.
        label: If provided, work in a labeled worktree (create or re-enter).
        resolved_path: Pre-resolved directory for path-based launch (bypasses config lookup).

    Raises:
        ProjectNotFoundError: If the project is not in the config.
        NoDirectoriesConfiguredError: If the project has no directories.
        DirectoryNotFoundError: If any project directories don't exist.
        PromptNotFoundError: If any required prompt files don't exist.
        NotAGitRepoError: If label provided but directory is not a git repo.
        WorktreeCommandError: If worktree creation fails.
    """
    if resolved_path is not None:
        project = ProjectConfig(dirs=[], working_style=DEFAULT_PATH_WORKING_STYLE)
        original_primary = resolved_path
        secondary_dirs: list[Path] = []
    else:
        project = resolve_project(project_name, config)
        if not project.dirs:
            raise NoDirectoriesConfiguredError(project_name)
        resolved_dirs = validate_dirs(project.dirs)
        original_primary = resolved_dirs[0]
        secondary_dirs = resolved_dirs[1:]

    # Handle worktree if label provided
    worktree_info: WorktreeInfo | None = None
    worktree_created = False
    repo_name = get_repo_name(original_primary) if is_git_repo(original_primary) else None

    if label:
        if not repo_name:
            raise NotAGitRepoError(original_primary)
        worktree_info, worktree_created = get_or_create_worktree(original_primary, project_name, label)
        primary_dir = worktree_info.path
    else:
        primary_dir = original_primary

    # Ensure scratch directory exists — keyed by repo name (or dir name for non-git)
    scratch_name = repo_name or original_primary.name
    _ensure_scratch_dir(scratch_name)

    # Assemble system prompt
    is_repo = repo_name is not None
    prompt_content, _ = prompts.assemble(
        project, primary_dir, secondary_dirs, is_repo=is_repo, scratch_name=scratch_name
    )

    # Build claude command
    cmd: list[str] = [CLAUDE_COMMAND]

    if resume:
        cmd.append("--resume")

    # Load bundled companion plugin (always)
    companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
    if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        cmd.extend(["--plugin-dir", str(companion_plugin_dir)])

    # Load observer plugin when configured
    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        cmd.extend(["--plugin-dir", str(observer_plugin_dir)])

    # Add any additional project directories
    for directory in secondary_dirs:
        cmd.extend(["--add-dir", str(directory)])

    if prompt_content:
        cmd.extend(["--system-prompt", prompt_content])

        # Persist assembled prompt so dispatch workers can reuse it.
        # Scope by label to avoid collisions between concurrent worktree sessions.
        prompt_key = f"{project_name}-{label}" if label else project_name
        prompt_path = USER_ASSEMBLED_PROMPTS_DIR / f"{prompt_key}.md"
        USER_ASSEMBLED_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_content)
        os.environ["BASECAMP_SYSTEM_PROMPT"] = str(prompt_path)

    # Load .env from the original project directory — worktrees won't have one
    dotenv_path = original_primary / ".env"
    load_dotenv(dotenv_path)

    # Change to primary project directory and execute claude
    os.chdir(primary_dir)

    # Set environment variables for hooks/prompts/MCP servers
    os.environ["BASECAMP_PROJECT"] = project_name
    os.environ["BASECAMP_REPO"] = repo_name or primary_dir.name

    if project.context:
        context_path = USER_CONTEXT_DIR / f"{project.context}.md"
        if context_path.exists():
            os.environ["BASECAMP_CONTEXT_FILE"] = str(context_path)

    startup_text = _build_startup_text(
        project_name,
        primary_dir,
        worktree_info,
        worktree_created=worktree_created,
        secondary_dirs=secondary_dirs,
        working_style=project.working_style,
    )

    # Collect env vars that need forwarding (tmux wrapping requires explicit
    # passing because tmux new-session inherits the server's env, not the client's).
    env_vars: dict[str, str] = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    for var in ("BASECAMP_PROJECT", "BASECAMP_REPO", "BASECAMP_CONTEXT_FILE", "BASECAMP_SYSTEM_PROMPT"):
        value = os.environ.get(var)
        if value:
            env_vars[var] = value

    session_name = f"bc-{project_name}-{label}" if label else f"bc-{project_name}"

    backend = resolve_launch_backend()
    backend.exec_session(cmd, startup_text=startup_text, env_vars=env_vars, session_name=session_name)
