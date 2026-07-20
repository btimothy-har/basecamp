"""Config-integrity checks: the document parses, is current, and validates.

This tier deliberately reads ``config.json`` raw (bypassing the lenient
:class:`~basecamp.core.settings.Settings` store, which returns ``{}`` for a
corrupt or non-object file), because that silent tolerance is exactly what a
doctor exists to surface. Section validation is collect-all and per-record, so
one bad project record is reported on its own line rather than aborting the run
on the first failure the way :func:`validate_document` does.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from basecamp.core.doctor import repair
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import CONFIG_VERSION, Settings
from basecamp.core.settings.schema import SECTIONS, validate_section

GROUP = "Config"


def raw_parse(settings: Settings) -> tuple[dict[str, Any] | None, Finding | None]:
    """Read ``config.json`` without the store's leniency to surface corruption.

    Returns ``({...}, None)`` for a valid object. Returns ``(None, finding)`` in
    the two states where the config-derived checks cannot run meaningfully: the
    file is absent (basecamp not set up — a benign warning) or present but not a
    JSON object (corruption the store hides — an error). In both the document is
    ``None`` so the aggregator skips the config-derived checks.
    """
    path = settings.path
    if not path.exists():
        summary = "basecamp is not set up — no config.json found."
        return None, Finding(GROUP, Severity.WARNING, summary, detail=f"run `basecamp setup` to create {path}.")
    try:
        text = path.read_text()
    except OSError as exc:
        return None, Finding(GROUP, Severity.ERROR, "config.json is unreadable.", detail=f"{path}: {exc}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        summary = "config.json is present but not valid JSON — the store silently reads it as empty."
        return None, Finding(GROUP, Severity.ERROR, summary, detail=f"{path}: {exc}")
    if not isinstance(parsed, dict):
        summary = "config.json is valid JSON but not an object — the store silently reads it as empty."
        return None, Finding(GROUP, Severity.ERROR, summary, detail=str(path))
    return parsed, None


def check_version(document: dict[str, Any], settings: Settings) -> list[Finding]:
    """Flag a missing or outdated config ``version`` (fixable)."""
    version = document.get("version")
    if version == CONFIG_VERSION:
        return []
    summary = (
        "config.json has no version key."
        if version is None
        else f"config.json version is {version!r}, expected {CONFIG_VERSION}."
    )
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            summary,
            remedy=Remedy.FIX,
            action=f"set version to {CONFIG_VERSION}",
            apply=lambda: repair.set_version(settings),
        )
    ]


def check_sections(document: dict[str, Any]) -> list[Finding]:
    """Validate each known section collect-all. Aliases are owned by the unused check."""
    findings: list[Finding] = []
    for name, section in SECTIONS.items():
        if name not in document or section.kind == "scalar_map" or section.model is None:
            continue
        value = document[name]
        if section.kind == "record_map":
            findings.extend(_check_records(name, section.model, value))
        else:
            findings.extend(_check_object(name, value))
    return findings


def _check_records(name: str, model: Any, value: Any) -> list[Finding]:
    if not isinstance(value, dict):
        return [Finding(GROUP, Severity.ERROR, f"{name} must be an object mapping names to records.")]
    findings: list[Finding] = []
    for key, record in value.items():
        try:
            model.model_validate(record)
        except ValidationError as exc:
            detail = exc.errors()[0]["msg"] if exc.errors() else str(exc)
            findings.append(Finding(GROUP, Severity.ERROR, f"{name}.{key} is invalid: {detail}"))
    return findings


def _check_object(name: str, value: Any) -> list[Finding]:
    try:
        validate_section(name, value)
    except LauncherError as exc:
        return [Finding(GROUP, Severity.ERROR, f"{name} section is invalid: {exc}")]
    return []
