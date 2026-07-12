"""Model-alias section of the basecamp config (``~/.pi/basecamp/config.json``).

The ``model_aliases`` section maps a short alias to a model string
(e.g. ``{"fast": "claude-haiku-4-5"}``). Basecamp (Python) is the sole writer;
the Pi extension reads the section in-process and routes its ``/model`` alias
writes here via ``basecamp config alias``. Other top-level sections are
preserved on every write.
"""

from __future__ import annotations

from typing import Any

from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import CONFIG_VERSION, Settings, settings

MODEL_ALIASES_SECTION = "model_aliases"


def load_model_aliases(config: Settings | None = None) -> dict[str, str]:
    """Return configured aliases, leniently skipping any malformed entries.

    Non-string or empty-after-trim keys/values are dropped (not fatal), and
    kept entries are trimmed to match the write path. A single bad entry never
    hides the good ones — the same lenient contract the Pi reader now honors.
    """
    active = config or settings
    raw = active.get_section(MODEL_ALIASES_SECTION)
    aliases: dict[str, str] = {}
    for alias, model in raw.items():
        if not isinstance(alias, str) or not isinstance(model, str):
            continue
        trimmed_alias, trimmed_model = alias.strip(), model.strip()
        if trimmed_alias and trimmed_model:
            aliases[trimmed_alias] = trimmed_model
    return aliases


def _normalize(alias: str, model: str) -> tuple[str, str]:
    """Trim and validate an alias/model pair, raising on empties."""
    trimmed_alias = alias.strip()
    trimmed_model = model.strip()
    if not trimmed_alias:
        msg = "Alias name must be a non-empty string."
        raise LauncherError(msg)
    if not trimmed_model:
        msg = "Model name must be a non-empty string."
        raise LauncherError(msg)
    return trimmed_alias, trimmed_model


def normalize_aliases(value: object) -> dict[str, str]:
    """Strictly validate a whole ``model_aliases`` section.

    Trims keys/values, rejects empties and non-strings, and rejects aliases
    that collide after trimming. Used by the config validation registry so a
    generic ``config set`` validates identically to ``config alias set``.
    """
    if not isinstance(value, dict):
        msg = "model_aliases must be an object mapping aliases to models."
        raise LauncherError(msg)

    normalized: dict[str, str] = {}
    for alias, model in value.items():
        if not isinstance(alias, str) or not isinstance(model, str):
            msg = "model_aliases must map string aliases to string models."
            raise LauncherError(msg)
        trimmed_alias, trimmed_model = _normalize(alias, model)
        if trimmed_alias in normalized:
            msg = f"Duplicate alias after trimming: {trimmed_alias}"
            raise LauncherError(msg)
        normalized[trimmed_alias] = trimmed_model
    return normalized


def set_alias(alias: str, model: str, config: Settings | None = None) -> tuple[str, str]:
    """Set (or overwrite) one alias, returning the stored (alias, model)."""
    active = config or settings
    trimmed_alias, trimmed_model = _normalize(alias, model)

    def mutate(data: dict[str, Any]) -> None:
        data["version"] = CONFIG_VERSION
        section = data.get(MODEL_ALIASES_SECTION)
        section = dict(section) if isinstance(section, dict) else {}
        section[trimmed_alias] = trimmed_model
        data[MODEL_ALIASES_SECTION] = section

    active.update(mutate)
    return trimmed_alias, trimmed_model


def remove_alias(alias: str, config: Settings | None = None) -> bool:
    """Remove one alias. Returns True if it existed, False otherwise."""
    active = config or settings
    trimmed_alias = alias.strip()
    removed = False

    def mutate(data: dict[str, Any]) -> None:
        nonlocal removed
        section = data.get(MODEL_ALIASES_SECTION)
        if isinstance(section, dict) and trimmed_alias in section:
            section = dict(section)
            section.pop(trimmed_alias, None)
            data["version"] = CONFIG_VERSION
            data[MODEL_ALIASES_SECTION] = section
            removed = True

    active.update(mutate)
    return removed


def rename_alias(old: str, new: str, config: Settings | None = None) -> tuple[str, str]:
    """Rename an alias in one flock'd write, returning the stored (new, model).

    Atomic: either both the remove-old and add-new land, or nothing does.
    Raises :class:`LauncherError` if ``old`` is missing, ``new`` is blank, or
    ``new`` already names a different alias.
    """
    active = config or settings
    trimmed_old = old.strip()
    trimmed_new = new.strip()
    if not trimmed_new:
        msg = "Alias name must be a non-empty string."
        raise LauncherError(msg)

    result: tuple[str, str] = ("", "")

    def mutate(data: dict[str, Any]) -> None:
        nonlocal result
        section = data.get(MODEL_ALIASES_SECTION)
        section = dict(section) if isinstance(section, dict) else {}
        if trimmed_old not in section:
            msg = f"No alias named {trimmed_old}."
            raise LauncherError(msg)
        if trimmed_new != trimmed_old and trimmed_new in section:
            msg = f"Alias {trimmed_new} already exists."
            raise LauncherError(msg)
        model = section.pop(trimmed_old)
        section[trimmed_new] = model
        data["version"] = CONFIG_VERSION
        data[MODEL_ALIASES_SECTION] = section
        result = (trimmed_new, model)

    active.update(mutate)
    return result
