"""Orchestration for `basecamp sync codex`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from basecamp.codex_sync.agents import AgentInstallResult, CodexAgentError, install_agents, preflight_agents
from basecamp.codex_sync.config import CodexConfigError, merge_config
from basecamp.codex_sync.skills import CodexSkillError, SkillInstallResult, install_skills, preflight_skills


class CodexSyncError(Exception):
    """Raised when Codex sync fails safely."""


@dataclass(frozen=True)
class CodexSyncResult:
    """Summary of a Codex sync run."""

    codex_home: Path
    config_path: Path
    agents_dir: Path
    skills_dir: Path
    config_changed: bool
    agents: AgentInstallResult
    skills: SkillInstallResult


def run_codex_sync(*, codex_home: Path | None = None, skills_dir: Path | None = None) -> CodexSyncResult:
    """Install user-level Codex config, custom agents, and skills."""
    active_codex_home = codex_home or _resolve_codex_home()
    agents_dir = active_codex_home / "agents"
    active_skills_dir = skills_dir or _resolve_skills_dir()
    config_path = active_codex_home / "config.toml"

    try:
        active_codex_home.mkdir(parents=True, exist_ok=True)
        agents_dir.mkdir(parents=True, exist_ok=True)
        active_skills_dir.mkdir(parents=True, exist_ok=True)
        preflight_agents(agents_dir)
        preflight_skills(active_skills_dir)
        config_changed = merge_config(config_path)
        agents = install_agents(agents_dir)
        skills = install_skills(active_skills_dir)
    except (OSError, CodexConfigError, CodexAgentError, CodexSkillError) as error:
        raise CodexSyncError(str(error)) from error

    return CodexSyncResult(
        codex_home=active_codex_home,
        config_path=config_path,
        agents_dir=agents_dir,
        skills_dir=active_skills_dir,
        config_changed=config_changed,
        agents=agents,
        skills=skills,
    )


def _resolve_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def _resolve_skills_dir() -> Path:
    return Path.home() / ".agents" / "skills"
