"""Per-repo environment configuration for basecamp-workspace.

Environments are keyed by repo name (``BASECAMP_REPO``) and persisted to the
root ``config.json`` ``environments`` section. Each environment currently
holds a ``setup`` command run when a new implementation worktree is created.
"""

from __future__ import annotations

from typing import Any

from basecamp_core.settings import CONFIG_VERSION, Settings, settings
from pydantic import BaseModel, ConfigDict

ENVIRONMENTS_SECTION = "environments"


class EnvironmentConfig(BaseModel):
    """Per-repo environment configuration."""

    model_config = ConfigDict(extra="forbid")

    setup: str | None = None


def load_environments(config: Settings | None = None) -> dict[str, EnvironmentConfig]:
    """Load all configured environments keyed by repo name."""
    active = config or settings
    raw = active.get_section(ENVIRONMENTS_SECTION)
    return {name: EnvironmentConfig.model_validate(data) for name, data in raw.items()}


def get_environment(repo_name: str, config: Settings | None = None) -> EnvironmentConfig | None:
    """Return the environment for ``repo_name``, or ``None`` if unset."""
    return load_environments(config).get(repo_name)


def set_environment(repo_name: str, env: EnvironmentConfig, config: Settings | None = None) -> None:
    """Persist the environment for ``repo_name``.

    A blank/absent setup command removes the entry — ``setup`` is currently the
    only field, so an environment with no command carries no information.
    """
    active = config or settings
    setup = env.setup.strip() if env.setup else ""

    def mutate(data: dict[str, Any]) -> None:
        data["version"] = CONFIG_VERSION
        section = data.get(ENVIRONMENTS_SECTION)
        section = dict(section) if isinstance(section, dict) else {}
        if setup:
            section[repo_name] = {"setup": setup}
        else:
            section.pop(repo_name, None)
        data[ENVIRONMENTS_SECTION] = section

    active.update(mutate)


def remove_environment(repo_name: str, config: Settings | None = None) -> None:
    """Remove the environment for ``repo_name`` if present."""
    active = config or settings

    def mutate(data: dict[str, Any]) -> None:
        section = data.get(ENVIRONMENTS_SECTION)
        if isinstance(section, dict) and repo_name in section:
            section = dict(section)
            section.pop(repo_name, None)
            data["version"] = CONFIG_VERSION
            data[ENVIRONMENTS_SECTION] = section

    active.update(mutate)
