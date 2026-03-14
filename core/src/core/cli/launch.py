"""Launch implementation for basecamp CLI."""

import os
import shlex
import shutil
from pathlib import Path

from dotenv import load_dotenv

from core.config import Config, ProjectConfig, resolve_project, validate_dirs
from core.constants import (
    CLAUDE_COMMAND,
    OBSERVER_CONFIG,
    SCRATCH_BASE,
    SCRIPT_DIR,
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
from core.ui import console
from core.utils import is_observer_configured

DEFAULT_PATH_WORKING_STYLE = "engineering"


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

    # Display start info
    console.print(f"\n[bold green]Starting Claude[/bold green] with project [cyan]{project_name}[/cyan]")
    console.print(f"  [dim]Primary:[/dim] {primary_dir}")
    if worktree_info:
        status = "new" if worktree_created else "existing"
        console.print(f"  [dim]Worktree:[/dim] {worktree_info.name} ({status})")
        console.print(f"  [dim]Branch:[/dim] {worktree_info.branch}")

    if secondary_dirs:
        console.print("  [dim]Added dirs:[/dim]")
        for directory in secondary_dirs:
            console.print(f"    • {directory}")

    if project.working_style:
        console.print(f"  [dim]Working style:[/dim] {project.working_style}")
    console.print()

    # Load .env from the original project directory — worktrees won't have one
    dotenv_path = original_primary / ".env"
    load_dotenv(dotenv_path)

    # Change to primary project directory and execute claude
    os.chdir(primary_dir)

    # Set environment variables for hooks/prompts/MCP servers
    os.environ["BASECAMP_REPO"] = repo_name or primary_dir.name

    if project.context:
        context_path = USER_CONTEXT_DIR / f"{project.context}.md"
        if context_path.exists():
            os.environ["BASECAMP_CONTEXT_FILE"] = str(context_path)

    # Wrap in tmux if not already inside a session — enables `basecamp dispatch`
    # to create worker panes without requiring manual tmux setup.
    # Env vars must be passed via -e because tmux new-session connects to an
    # existing server whose processes inherit the server's env, not the client's.
    if not os.environ.get("TMUX") and shutil.which("tmux"):
        session_name = f"bc-{project_name}"
        claude_cmd = shlex.join(cmd)
        shell_cmd = (
            "tmux set -g mouse on && "
            "tmux set -g history-limit 50000 && "
            f"export GPG_TTY=$(tty) && exec {claude_cmd}"
        )
        tmux_cmd = ["tmux", "new-session", "-s", session_name]
        # Forward basecamp env vars into the tmux session
        for var in ("BASECAMP_REPO", "BASECAMP_CONTEXT_FILE"):
            value = os.environ.get(var)
            if value:
                tmux_cmd.extend(["-e", f"{var}={value}"])
        tmux_cmd.extend(["bash", "-c", shell_cmd])
        os.execvp("tmux", tmux_cmd)
    else:
        os.execvp(CLAUDE_COMMAND, cmd)
