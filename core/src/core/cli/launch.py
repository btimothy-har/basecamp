"""Launch pi with a basecamp project configuration.

Thin launcher — resolves the project directory, changes to it, and execs
pi with --project. The extension handles prompt assembly, env vars, and
all other session setup via its session_start hook.
"""

from __future__ import annotations

import os

from core.config import Config, resolve_project, validate_dirs
from core.exceptions import NoDirectoriesConfiguredError

PI_COMMAND = "pi"


def execute_launch(
    project_name: str,
    config: Config,
    *,
    label: str | None = None,
    style: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Launch a pi session for the given project.

    Resolves the project's primary directory, chdir's into it, and execs pi
    with the appropriate flags. Does not return — replaces the current process.
    """
    project = resolve_project(project_name, config)
    if not project.dirs:
        raise NoDirectoriesConfiguredError(project_name)

    primary_dir = validate_dirs(project.dirs)[0]

    cmd: list[str] = [PI_COMMAND, "--project", project_name]
    if label:
        cmd.extend(["--label", label])
    if style:
        cmd.extend(["--style", style])
    if extra_args:
        cmd.extend(extra_args)

    os.chdir(primary_dir)
    os.execvp(cmd[0], cmd)
