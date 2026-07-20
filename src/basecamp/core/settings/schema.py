"""The config-section registry — one descriptor per top-level ``config.json`` section.

This is the single source of truth for *what sections exist* and *how each is
validated*. Both config front-ends — the generic ``config set|unset|edit``
plumbing and the typed ``config project|env|alias`` porcelain — run a mutated
section through this registry before the flock'd write, so the two paths
accept/reject identically. Cross-cutting features (validation, the interactive
console, a future ``config doctor``) iterate :data:`REGISTRY` instead of
re-enumerating the sections by hand — adding a section is one entry here, not an
edit spread across every layer.

The section *models* live in :mod:`basecamp.core.models`; this module only maps
each section name to its model + kind and owns the validation policy. Validators
raise :class:`LauncherError` on bad input (pydantic errors are wrapped) so the
CLI's error handling stays uniform.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from basecamp.core.exceptions import LauncherError
from basecamp.core.model_aliases import normalize_aliases
from basecamp.core.models import EnvironmentConfig, LogseqConfig, ProjectConfig

#: How a section's value is shaped, which selects its validation strategy.
#:   * ``record_map`` — a ``{name: record}`` map; each record validates against
#:     ``model`` independently, so a malformed sibling never blocks an edit to a
#:     different record.
#:   * ``object`` — a single object validated whole against ``model``.
#:   * ``scalar_map`` — a flat map validated by ``normalize`` (e.g. aliases).
SectionKind = Literal["record_map", "scalar_map", "object"]


@dataclass(frozen=True)
class ConfigSection:
    """One top-level section of ``config.json`` and how to validate it."""

    name: str
    label: str
    kind: SectionKind
    model: type[BaseModel] | None = None
    normalize: Callable[[Any], Any] | None = None


REGISTRY: tuple[ConfigSection, ...] = (
    ConfigSection("projects", "Projects", "record_map", model=ProjectConfig),
    ConfigSection("environments", "Environments", "record_map", model=EnvironmentConfig),
    ConfigSection("model_aliases", "Model aliases", "scalar_map", normalize=normalize_aliases),
    ConfigSection("logseq", "Logseq", "object", model=LogseqConfig),
)

#: Registry indexed by section name, for O(1) lookup by the validators below.
SECTIONS: dict[str, ConfigSection] = {section.name: section for section in REGISTRY}


def _validate_record(section: str, key: str, record: Any, model: type[BaseModel]) -> dict[str, Any]:
    """Validate + normalize a single record of a record-map section."""
    try:
        return model.model_validate(record).model_dump()
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"] if exc.errors() else str(exc)
        msg = f"Invalid {section}.{key}: {detail}"
        raise LauncherError(msg) from exc


def _validate_record_map(name: str, value: Any, model: type[BaseModel]) -> dict[str, Any]:
    """Validate a whole ``{key: record}`` map against a pydantic model."""
    if not isinstance(value, dict):
        msg = f"{name} must be an object mapping names to records."
        raise LauncherError(msg)
    return {key: _validate_record(name, key, record, model) for key, record in value.items()}


def _validate_object(name: str, value: Any, model: type[BaseModel]) -> dict[str, Any]:
    """Validate a single-object section, rejecting unknown keys like the records."""
    if not isinstance(value, dict):
        msg = f"{name} must be an object."
        raise LauncherError(msg)
    try:
        return model.model_validate(value).model_dump(exclude_none=True)
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"] if exc.errors() else str(exc)
        msg = f"Invalid {name}: {detail}"
        raise LauncherError(msg) from exc


def _validate_with(section: ConfigSection, value: Any) -> Any:
    """Dispatch a section's value to the validator its ``kind`` selects."""
    model = section.model
    if model is not None and section.kind == "record_map":
        return _validate_record_map(section.name, value, model)
    if model is not None and section.kind == "object":
        return _validate_object(section.name, value, model)
    if section.normalize is not None:
        return section.normalize(value)
    msg = f"Section {section.name} is misconfigured."  # unreachable for a valid REGISTRY
    raise LauncherError(msg)


def validate_section(name: str, value: Any) -> Any:
    """Validate + normalize one top-level section, or pass it through.

    Unregistered sections (``version``, ``install_dir``, future freeform keys)
    pass through untouched. Raises :class:`LauncherError` if a known section is
    malformed.
    """
    section = SECTIONS.get(name)
    if section is None:
        return value
    return _validate_with(section, value)


def validate_document(document: Any) -> dict[str, Any]:
    """Validate every known section of a whole config document.

    Returns the document with validated sections normalized in place. Raises
    :class:`LauncherError` on a non-object document or any bad section.
    """
    if not isinstance(document, dict):
        msg = "Config must be a JSON object."
        raise LauncherError(msg)
    result = dict(document)
    for name in SECTIONS:
        if name in result:
            result[name] = validate_section(name, result[name])
    return result


def validate_touched(document: dict[str, Any], segments: list[str]) -> None:
    """Validate, in place, only the scope a ``set``/``unset`` touched.

    Editing a record inside a record-map section validates just that record, so a
    malformed sibling record can't block an unrelated edit. Object sections,
    scalar-map sections, and whole-section writes validate the whole section. A
    removed record is skipped (nothing to check).
    """
    section = SECTIONS.get(segments[0])
    if section is None:
        return
    model = section.model
    if model is not None and section.kind == "record_map" and len(segments) >= 2:
        records = document.get(section.name)
        key = segments[1]
        if isinstance(records, dict) and key in records:
            records[key] = _validate_record(section.name, key, records[key], model)
        return
    if section.name in document:
        document[section.name] = validate_section(section.name, document[section.name])
