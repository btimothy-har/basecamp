"""Per-section validation for the unified ``config.json``.

This is the single validation layer shared by both config front-ends: the
generic ``config set|unset|edit`` plumbing and the typed ``config project|env|
alias`` porcelain both run a mutated section through :func:`validate_section`
before the flock'd write, so the two paths accept/reject identically.

It aggregates schema across domains — the core project/alias schemas and the
workspace environment schema — so it lives in the config-management layer
(``core/cli``) rather than in core's primitives, alongside the porcelain that
already reaches into ``workspace``. Validators raise :class:`LauncherError` on
bad input (pydantic errors are wrapped) so the CLI's error handling stays
uniform.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from basecamp.core.exceptions import LauncherError
from basecamp.core.model_aliases import normalize_aliases
from basecamp.core.projects import ProjectConfig
from basecamp.workspace.environments import EnvironmentConfig

#: Top-level sections that carry a validator. Anything else (``version``,
#: ``install_dir``, future freeform keys) is passed through untouched.
VALIDATED_SECTIONS = ("projects", "environments", "model_aliases", "logseq")


def _validate_records(name: str, value: Any, model: type) -> dict[str, Any]:
    """Validate a ``{key: record}`` map against a pydantic model."""
    if not isinstance(value, dict):
        msg = f"{name} must be an object mapping names to records."
        raise LauncherError(msg)
    try:
        return {key: model.model_validate(record).model_dump() for key, record in value.items()}
    except ValidationError as exc:
        msg = f"Invalid {name}: {exc.errors()[0]['msg'] if exc.errors() else exc}"
        raise LauncherError(msg) from exc


def _validate_logseq(value: Any) -> dict[str, Any]:
    """Validate the ``logseq`` section: an object with an optional string graph_dir."""
    if not isinstance(value, dict):
        msg = "logseq must be an object."
        raise LauncherError(msg)
    graph_dir = value.get("graph_dir")
    if graph_dir is not None and not isinstance(graph_dir, str):
        msg = "logseq.graph_dir must be a string."
        raise LauncherError(msg)
    return value


def validate_section(name: str, value: Any) -> Any:
    """Validate + normalize one top-level section, or pass it through.

    Raises :class:`LauncherError` if the section is malformed.
    """
    if name == "projects":
        return _validate_records(name, value, ProjectConfig)
    if name == "environments":
        return _validate_records(name, value, EnvironmentConfig)
    if name == "model_aliases":
        return normalize_aliases(value)
    if name == "logseq":
        return _validate_logseq(value)
    return value


def validate_document(document: Any) -> dict[str, Any]:
    """Validate every known section of a whole config document.

    Returns the document with validated sections normalized in place. Raises
    :class:`LauncherError` on a non-object document or any bad section.
    """
    if not isinstance(document, dict):
        msg = "Config must be a JSON object."
        raise LauncherError(msg)
    result = dict(document)
    for name in VALIDATED_SECTIONS:
        if name in result:
            result[name] = validate_section(name, result[name])
    return result
