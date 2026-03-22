"""Build a mutated Claude settings file for basecamp sessions.

Reads the user's ~/.claude/settings.json, strips auth helpers, merges
project .env vars, and injects BASECAMP_* env vars. The result is written
to ~/.basecamp/.cached/{project}/settings.json and passed to Claude CLI
via --settings.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from core.constants import CACHE_DIR, CLAUDE_USER_SETTINGS, SCRATCH_BASE
from core.utils import atomic_write_json

# Keys to strip from user settings — basecamp sessions always use
# ANTHROPIC_API_KEY from .env rather than key helpers.
_STRIPPED_KEYS = {"apiKeyHelper"}

# Tasks dir is under SCRATCH_BASE — session_id isn't known at launch
# so we pre-authorize the whole tree.
_TASKS_DIR = SCRATCH_BASE / "tasks"


def _load_user_settings() -> dict[str, Any]:
    """Read ~/.claude/settings.json, returning empty dict if absent."""
    try:
        return json.loads(CLAUDE_USER_SETTINGS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def build_session_settings(
    *,
    project_name: str,
    repo_name: str,
    scratch_name: str,
    dotenv_path: Path,
    system_prompt_path: str | None = None,
    context_file_path: str | None = None,
    observer_enabled: bool = False,
    label: str | None = None,
) -> Path:
    """Produce a mutated settings file for a basecamp session.

    Returns the path to the cached settings file.
    """
    settings = _load_user_settings()

    for key in _STRIPPED_KEYS:
        settings.pop(key, None)

    # Merge .env vars into settings.env (user settings env takes lower priority)
    dotenv_vars = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    env_block: dict[str, str] = dotenv_vars
    env_block.update(settings.get("env", {}))
    settings["env"] = env_block

    # Pre-authorize scratch and tasks directories
    scratch_dir = SCRATCH_BASE / scratch_name
    permissions = settings.setdefault("permissions", {})
    allow: list[str] = list(permissions.get("allow", []))
    for directory in (scratch_dir, _TASKS_DIR):
        allow.extend(f"{tool}({directory}/**)" for tool in ("Read", "Write", "Edit"))
    permissions["allow"] = allow

    # Inject BASECAMP_* env vars
    cache_dir = CACHE_DIR / project_name / label if label else CACHE_DIR / project_name
    settings_path = cache_dir / "settings.json"

    basecamp_env: dict[str, str] = {
        "BASECAMP_PROJECT": project_name,
        "BASECAMP_REPO": repo_name,
        "BASECAMP_SCRATCH_DIR": str(scratch_dir),
        "BASECAMP_SETTINGS_FILE": str(settings_path),
    }
    if system_prompt_path:
        basecamp_env["BASECAMP_SYSTEM_PROMPT"] = system_prompt_path
    if context_file_path:
        basecamp_env["BASECAMP_CONTEXT_FILE"] = context_file_path
    if observer_enabled:
        basecamp_env["BASECAMP_OBSERVER_ENABLED"] = "1"

    settings["env"].update(basecamp_env)

    atomic_write_json(settings_path, settings, mode=0o600)
    return settings_path
