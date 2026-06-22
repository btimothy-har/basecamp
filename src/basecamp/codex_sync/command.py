"""Orchestration for `basecamp sync codex`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from basecamp.codex_sync.agents import AgentInstallResult, CodexAgentError, install_agents, preflight_agents
from basecamp.codex_sync.assets import SCRATCH_ROOT
from basecamp.codex_sync.config import CodexConfigError, merge_config

DEFAULT_SCRATCH_DIR = Path(SCRATCH_ROOT)


class CodexSyncError(Exception):
    """Raised when Codex sync fails safely."""


@dataclass(frozen=True)
class CodexSyncResult:
    """Summary of a Codex sync run."""

    codex_home: Path
    config_path: Path
    agents_dir: Path
    scratch_dir: Path
    config_changed: bool
    agents: AgentInstallResult


def run_codex_sync(*, codex_home: Path | None = None, scratch_dir: Path | None = None) -> CodexSyncResult:
    """Install user-level Codex config, writable scratch root, and agents."""
    active_codex_home = codex_home or _resolve_codex_home()
    active_scratch_dir = scratch_dir or DEFAULT_SCRATCH_DIR
    agents_dir = active_codex_home / "agents"
    config_path = active_codex_home / "config.toml"

    try:
        active_codex_home.mkdir(parents=True, exist_ok=True)
        agents_dir.mkdir(parents=True, exist_ok=True)
        _ensure_scratch_dir(active_scratch_dir)
        preflight_agents(agents_dir)
        config_changed = merge_config(config_path, writable_root=str(active_scratch_dir))
        agents = install_agents(agents_dir)
    except (OSError, CodexConfigError, CodexAgentError) as error:
        raise CodexSyncError(str(error)) from error

    return CodexSyncResult(
        codex_home=active_codex_home,
        config_path=config_path,
        agents_dir=agents_dir,
        scratch_dir=active_scratch_dir,
        config_changed=config_changed,
        agents=agents,
    )


def _ensure_scratch_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _resolve_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"
