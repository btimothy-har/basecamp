"""Unused-config checks: dead keys, orphaned records, and abandoned locations.

The line here follows the repair policy exactly. *Known-dead* config — the
retired ``installed_modules`` key, environment records carrying no command,
alias entries the read path already ignores — is fixable losslessly, because
removing it changes nothing that was in effect. *Ambiguous* config — an unknown
top-level key, files left in the pre-rearchitecture override location — is
report-only, because deleting it would be a guess or would drop authored
content. Section names come from the core-owned config registry, not from the
domains that own them.
"""

from __future__ import annotations

from typing import Any

from basecamp.core.doctor import repair
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.doctor.locations import Locations
from basecamp.core.model_aliases import MODEL_ALIASES_SECTION, load_model_aliases
from basecamp.core.models import EnvironmentConfig
from basecamp.core.settings import Settings
from basecamp.core.settings.schema import REGISTRY, SECTIONS

GROUP = "Unused config"

_INSTALLED_MODULES_KEY = "installed_modules"
_ROOT_KEYS = frozenset({"version", "install_dir"})
_KNOWN_TOP_LEVEL = _ROOT_KEYS | set(SECTIONS) | {_INSTALLED_MODULES_KEY}
_ENVIRONMENTS_SECTION = next(
    (section.name for section in REGISTRY if section.model is EnvironmentConfig),
    "environments",
)


def check_unused(document: dict[str, Any], settings: Settings, locations: Locations) -> list[Finding]:
    """Run all unused-config checks against the current config and filesystem."""
    findings: list[Finding] = []
    findings.extend(_check_installed_modules(document, settings))
    findings.extend(_check_unknown_keys(document))
    findings.extend(_check_empty_environments(document, settings))
    findings.extend(_check_malformed_aliases(document, settings))
    findings.extend(_check_legacy_overrides(locations))
    return findings


def _check_installed_modules(document: dict[str, Any], settings: Settings) -> list[Finding]:
    if _INSTALLED_MODULES_KEY not in document:
        return []
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            "installed_modules is a retired key the store already discards on write.",
            remedy=Remedy.FIX,
            action="remove installed_modules",
            apply=lambda: repair.drop_top_level_key(settings, _INSTALLED_MODULES_KEY),
        )
    ]


def _check_unknown_keys(document: dict[str, Any]) -> list[Finding]:
    unknown = [key for key in document if key not in _KNOWN_TOP_LEVEL]
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            f"unknown top-level config key: {key!r} (left as-is — remove it with `basecamp config unset`).",
        )
        for key in unknown
    ]


def _check_empty_environments(document: dict[str, Any], settings: Settings) -> list[Finding]:
    section = document.get(_ENVIRONMENTS_SECTION)
    if not isinstance(section, dict):
        return []
    findings: list[Finding] = []
    for repo, record in section.items():
        if not isinstance(record, dict):
            continue
        setup = record.get("setup")
        if isinstance(setup, str) and setup.strip():
            continue
        findings.append(
            Finding(
                GROUP,
                Severity.WARNING,
                f"environment {repo!r} carries no setup command.",
                remedy=Remedy.FIX,
                action=f"remove empty environment {repo!r}",
                apply=lambda repo=repo: repair.drop_record(settings, _ENVIRONMENTS_SECTION, repo),
            )
        )
    return findings


def _check_malformed_aliases(document: dict[str, Any], settings: Settings) -> list[Finding]:
    raw = document.get(MODEL_ALIASES_SECTION)
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return [_malformed_aliases_finding("model_aliases is not an object.", settings)]
    dropped = len(raw) - len(load_model_aliases(settings))
    if dropped <= 0:
        return []
    summary = f"model_aliases has {dropped} malformed entr(y/ies) the read path ignores."
    return [_malformed_aliases_finding(summary, settings)]


def _malformed_aliases_finding(summary: str, settings: Settings) -> Finding:
    return Finding(
        GROUP,
        Severity.WARNING,
        summary,
        remedy=Remedy.FIX,
        action="prune malformed model aliases",
        apply=lambda: repair.prune_malformed_aliases(settings),
    )


def _check_legacy_overrides(locations: Locations) -> list[Finding]:
    legacy = locations.legacy_overrides_dir
    if not legacy.is_dir() or not any(path.is_file() for path in legacy.rglob("*")):
        return []
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            "override files remain in the pre-rearchitecture location (not migrated automatically).",
            detail=(
                f"{legacy} — move context/styles/prompts up to {locations.basecamp_dir} by hand; not deleted for you."
            ),
        )
    ]
