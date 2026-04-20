"""Launch pi with a basecamp project configuration.

Thin launcher — resolves the project directory, changes to it, and execs
pi with --project. The extension handles prompt assembly, env vars, and
all other session setup via its session_start hook.
"""

from __future__ import annotations

import os

from basecamp.config import ProjectConfig, resolve_project, validate_dirs
from basecamp.exceptions import NoDirectoriesConfiguredError

PI_COMMAND = "pi"


def execute_launch(
    project_name: str | None,
    projects: dict[str, ProjectConfig] | None,
    *,
    label: str | None = None,
    style: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """Launch a pi session for the given project.

    If project_name is None, launches pi in the current directory without
    a project. Otherwise resolves the project's primary directory, chdir's
    into it, and execs pi with the appropriate flags.

    Does not return — replaces the current process.
    """
    cmd: list[str] = [PI_COMMAND]

    if project_name is not None:
        assert projects is not None
        project = resolve_project(project_name, projects)
        if not project.dirs:
            raise NoDirectoriesConfiguredError(project_name)

        primary_dir = validate_dirs(project.dirs)[0]
        cmd.extend(["--project", project_name])
        os.chdir(primary_dir)

    if label:
        cmd.extend(["--label", label])
    if style:
        cmd.extend(["--style", style])
    if extra_args:
        cmd.extend(extra_args)

    os.execvp(cmd[0], cmd)
