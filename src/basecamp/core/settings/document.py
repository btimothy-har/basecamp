"""Generic dotted-path access to the unified ``config.json``.

The ``git config``-style plumbing under ``basecamp config``: read, set, unset,
and whole-file edit on dotted keys (``model_aliases.fast``, ``logseq.graph_dir``,
``projects.demo.repo_root``). Every mutation runs the touched section through the
:mod:`~basecamp.core.settings.schema` registry before the flock'd write, so
generic edits validate exactly like the typed porcelain. The root :data:`settings`
singleton is the sole writer.

Lives in the ``core/settings`` layer beside the registry it depends on; the CLI
(``config_cli``) is a thin click surface over these functions.
"""

from __future__ import annotations

import json
from typing import Any

import click

from basecamp.core.exceptions import LauncherError
from basecamp.core.settings.schema import validate_document, validate_touched
from basecamp.core.settings.store import CONFIG_VERSION, Settings, settings

_MISSING = object()

#: Top-level keys basecamp owns; the generic set/unset plumbing won't touch them.
_MANAGED_KEYS = frozenset({"version"})


def _reject_if_managed(section: str) -> None:
    if section in _MANAGED_KEYS:
        msg = f"`{section}` is managed by basecamp and cannot be changed directly."
        raise LauncherError(msg)


def split_key(key: str) -> list[str]:
    """Split a dotted key into non-empty segments."""
    segments = [segment for segment in key.split(".") if segment]
    if not segments:
        msg = "Key must be a non-empty dotted path (e.g. model_aliases.fast)."
        raise LauncherError(msg)
    return segments


def get_value(key: str, config: Settings | None = None) -> Any:
    """Return the value at a dotted key, raising if it is absent."""
    active = config or settings
    node: Any = active.read()
    for segment in split_key(key):
        if not isinstance(node, dict) or segment not in node:
            msg = f"Key not found: {key}"
            raise LauncherError(msg)
        node = node[segment]
    return node


def set_value(key: str, raw: str, *, as_json: bool = False, config: Settings | None = None) -> Any:
    """Set a dotted key to a value, validating its section before writing.

    ``raw`` is stored as a string unless ``as_json`` parses it (for null, lists,
    numbers, or nested objects). Returns the stored value.
    """
    active = config or settings
    segments = split_key(key)
    _reject_if_managed(segments[0])
    if as_json:
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"Invalid JSON value: {exc}"
            raise LauncherError(msg) from exc
    else:
        value = raw

    def mutate(document: dict[str, Any]) -> None:
        node = document
        for segment in segments[:-1]:
            existing = node.get(segment, _MISSING)
            if existing is _MISSING:
                node[segment] = {}
            elif not isinstance(existing, dict):
                msg = f"Cannot set {key}: {segment} is a value, not a section."
                raise LauncherError(msg)
            node = node[segment]
        node[segments[-1]] = value
        validate_touched(document, segments)
        document["version"] = CONFIG_VERSION

    active.update(mutate)
    return value


def unset_value(key: str, config: Settings | None = None) -> bool:
    """Delete a dotted key. Re-validates its section. Returns True if removed."""
    active = config or settings
    segments = split_key(key)
    _reject_if_managed(segments[0])
    removed = False

    def mutate(document: dict[str, Any]) -> None:
        nonlocal removed
        node: Any = document
        for segment in segments[:-1]:
            node = node.get(segment) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                return
        if isinstance(node, dict) and segments[-1] in node:
            del node[segments[-1]]
            removed = True
            validate_touched(document, segments)
            document["version"] = CONFIG_VERSION

    active.update(mutate)
    return removed


def replace_document(document: Any, config: Settings | None = None) -> None:
    """Validate and atomically replace the whole config document."""
    validated = validate_document(document)
    validated["version"] = CONFIG_VERSION
    active = config or settings

    def mutate(data: dict[str, Any]) -> None:
        data.clear()
        data.update(validated)

    active.update(mutate)


def edit_document(config: Settings | None = None) -> bool:
    """Open ``config.json`` in ``$EDITOR``; validate + persist on save.

    Returns False if the editor was aborted or nothing changed. Raises
    :class:`LauncherError` on invalid JSON or a failing section (never persists
    a broken document).
    """
    active = config or settings
    current = f"{json.dumps(active.read(), indent=2)}\n"
    edited = click.edit(current, extension=".json")
    if edited is None or edited == current:
        return False
    try:
        document = json.loads(edited)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON — not saved: {exc}"
        raise LauncherError(msg) from exc
    replace_document(document, active)
    return True
