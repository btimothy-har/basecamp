"""System prompt loading and assembly."""

import datetime
import os
import platform
from importlib import resources
from pathlib import Path

from core.config import ProjectConfig
from core.constants import (
    SCRATCH_BASE,
    USER_PROMPTS_DIR,
)
from core.git import generate_git_status, get_remote_url
from core.prompts import working_styles


def _load_package_prompt(filename: str) -> str:
    """Load a prompt file from the core.prompts._system_prompts package."""
    return resources.files("core.prompts._system_prompts").joinpath(filename).read_text()


def _load_environment_prompt() -> tuple[str, str]:
    """Load environment prompt, checking user dir before package default.

    Returns:
        Tuple of (content, source) where source identifies the origin.
    """
    user_path = USER_PROMPTS_DIR / "environment.md"
    if user_path.exists():
        return user_path.read_text(), "prompts/environment.md"
    return _load_package_prompt("environment.md"), "core.prompts/environment.md"


def _load_system_prompt() -> tuple[str, str]:
    """Load system prompt, checking user dir before package default.

    Returns:
        Tuple of (content, source) where source identifies the origin.
    """
    user_path = USER_PROMPTS_DIR / "system.md"
    if user_path.exists():
        return user_path.read_text(), "prompts/system.md"
    return _load_package_prompt("system.md"), "core.prompts/system.md"


def generate_env_block(
    primary_dir: Path,
    additional_dirs: list[Path],
    *,
    is_repo: bool,
    remote_url: str | None,
    scratch_name: str,
) -> str:
    """Generate runtime environment info (paths, platform, date)."""
    user = os.environ.get("USER", "unknown")
    lines = [
        f"User: {user}",
        f"Working directory: {primary_dir}",
    ]
    if additional_dirs:
        lines.append(f"Additional directories: {', '.join(str(d) for d in additional_dirs)}")
    lines.append(f"Is directory a git repo: {'Yes' if is_repo else 'No'}")
    if remote_url:
        lines.append(f"Git remote: {remote_url}")
    lines.extend(
        [
            f"Platform: {platform.system().lower()}",
            f"OS Version: {platform.system()} {platform.release()}",
            f"Today's date: {datetime.datetime.now(tz=datetime.UTC).date().isoformat()}",
            "",
            f"Scratch: {SCRATCH_BASE / scratch_name}",
        ]
    )
    return "\n".join(lines)


def build_runtime_preamble(
    primary_dir: Path,
    additional_dirs: list[Path],
    *,
    is_repo: bool,
    scratch_name: str,
) -> tuple[str, str]:
    """Build the runtime preamble: env block + environment.md + git status.

    This is the common first layer shared by all prompt assembly paths
    (project launch, reflect, etc.).

    Returns:
        Tuple of (preamble_content, environment_source).
    """
    remote_url = get_remote_url(primary_dir) if is_repo else None
    env_block = generate_env_block(
        primary_dir, additional_dirs, is_repo=is_repo, remote_url=remote_url, scratch_name=scratch_name
    )
    git_status = generate_git_status(primary_dir) if is_repo else None

    environment_content, environment_source = _load_environment_prompt()
    parts = [env_block, environment_content.strip()]
    if git_status:
        parts.append(git_status)

    return "\n\n".join(parts), environment_source


def assemble(
    project: ProjectConfig,
    primary_dir: Path,
    additional_dirs: list[Path],
    *,
    is_repo: bool,
    scratch_name: str,
) -> tuple[str, list[str]]:
    """Assemble the full system prompt for a project.

    Args:
        project: The project configuration.
        primary_dir: The resolved primary directory.
        additional_dirs: Additional project directories (--add-dir).
        is_repo: Whether the primary directory is a git repo.
        scratch_name: Identifier for the scratch directory (repo name or dir name).

    Returns:
        A tuple of (prompt_content, prompt_sources).

    Raises:
        PromptNotFoundError: If a specified working style doesn't exist anywhere.
    """
    prompt_parts: list[str] = []
    prompt_sources: list[str] = []

    # 1. Runtime context first (paths, platform), then environment guidelines
    preamble, environment_source = build_runtime_preamble(
        primary_dir, additional_dirs, is_repo=is_repo, scratch_name=scratch_name
    )
    prompt_parts.append(preamble)
    prompt_sources.append(environment_source)

    # 2. Include working style if specified (user dir takes precedence over package)
    if project.working_style:
        content, style_source = working_styles.load(project.working_style)
        prompt_parts.append(content.strip())
        prompt_sources.append(style_source)

    # 3. System prompt (user dir takes precedence over package default)
    system_content, system_source = _load_system_prompt()
    prompt_parts.append(system_content.strip())
    prompt_sources.append(system_source)

    prompt_content = "\n\n".join(prompt_parts)
    return prompt_content, prompt_sources
