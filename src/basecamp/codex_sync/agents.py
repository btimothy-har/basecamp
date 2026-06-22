"""Codex specialist agent installation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomlkit

from basecamp.codex_sync.assets import AGENTS, AgentDefinition

MANAGED_MARKER_BODY = "Managed by basecamp codex sync; source=basecamp.codex_sync v1"
MANAGED_MARKER = f"# {MANAGED_MARKER_BODY}"


class CodexAgentError(Exception):
    """Raised when Codex agents cannot be safely installed."""


class UnmanagedAgentConflictError(CodexAgentError):
    """Raised when an unmanaged same-name agent file exists."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Refusing to overwrite unmanaged Codex agent file: {path}")


@dataclass(frozen=True)
class AgentInstallResult:
    """Summary of installed Codex agents."""

    installed: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.installed + self.updated + self.unchanged


def install_agents(agents_dir: Path) -> AgentInstallResult:
    """Install managed specialist agent TOML files."""
    installed = 0
    updated = 0
    unchanged = 0

    for agent in AGENTS:
        path = agents_dir / agent.filename
        content = _render_agent(agent)

        if not path.exists():
            path.write_text(content)
            installed += 1
            continue

        existing = path.read_text()
        if MANAGED_MARKER not in existing:
            raise UnmanagedAgentConflictError(path)

        if existing == content:
            unchanged += 1
            continue

        path.write_text(content)
        updated += 1

    return AgentInstallResult(installed=installed, updated=updated, unchanged=unchanged)


def _render_agent(agent: AgentDefinition) -> str:
    document = tomlkit.document()
    document.add(tomlkit.comment(MANAGED_MARKER_BODY))
    document["name"] = agent.name
    document["description"] = agent.description
    document["developer_instructions"] = agent.developer_instructions
    return tomlkit.dumps(document)
