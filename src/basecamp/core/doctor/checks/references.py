"""Referential checks: config points at things that actually exist on disk.

Repo roots and additional dirs are stored home-relative, so they resolve
against ``locations.home``; styles and contexts resolve against the extension's
bundled styles (under ``install_dir``) plus the user override dirs. Nothing here
is auto-repaired — a path that points nowhere needs a human to re-point it — so
every finding is report-only except the scaffold-dirs one, which ``--fix`` can
recreate losslessly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from basecamp.core.doctor import repair
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.doctor.locations import Locations
from basecamp.core.projects import PROJECTS_SECTION, ProjectConfig
from basecamp.core.settings import Settings

GROUP = "References"


def check_references(settings: Settings, locations: Locations) -> list[Finding]:
    """Run all referential checks against the current config and filesystem."""
    findings: list[Finding] = []
    findings.extend(_check_scaffold_dirs(locations))
    findings.extend(_check_install_dir(settings))
    findings.extend(_check_logseq(settings))
    findings.extend(_check_projects(settings, locations))
    return findings


def _check_scaffold_dirs(locations: Locations) -> list[Finding]:
    missing = [path for path in locations.scaffold_dirs if not path.exists()]
    if not missing:
        return []
    names = ", ".join(path.name for path in missing)
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            f"user override directories are missing: {names}.",
            remedy=Remedy.FIX,
            action="scaffold override directories",
            apply=lambda: repair.scaffold_dirs(locations.scaffold_dirs),
        )
    ]


def _check_install_dir(settings: Settings) -> list[Finding]:
    install_dir = settings.install_dir
    if install_dir and not Path(install_dir).is_dir():
        return [Finding(GROUP, Severity.WARNING, f"install_dir does not exist: {install_dir}.")]
    return []


def _check_logseq(settings: Settings) -> list[Finding]:
    graph_dir = settings.get_section("logseq").get("graph_dir")
    if not isinstance(graph_dir, str) or not graph_dir.strip():
        return []
    if not Path(graph_dir).expanduser().is_dir():
        return [Finding(GROUP, Severity.WARNING, f"logseq.graph_dir does not exist: {graph_dir}.")]
    return []


def _check_projects(settings: Settings, locations: Locations) -> list[Finding]:
    # Validate each record independently rather than via load_projects(), whose
    # all-or-nothing raise on the first bad record would suppress reference
    # checks for every other, valid project. Invalid records are already
    # reported by the integrity check, so they are skipped here.
    raw = settings.get_section(PROJECTS_SECTION)
    styles = _available_styles(settings, locations)
    contexts = _available_contexts(locations)
    findings: list[Finding] = []
    for name, data in raw.items():
        try:
            project = ProjectConfig.model_validate(data)
        except ValidationError:
            continue
        findings.extend(_check_project(name, project, settings, locations, styles, contexts))
    return findings


def _check_project(
    name: str,
    project: ProjectConfig,
    settings: Settings,
    locations: Locations,
    styles: set[str],
    contexts: set[str],
) -> list[Finding]:
    findings = _check_repo_root(name, project.repo_root, locations)
    findings.extend(_check_repo_root_storage(name, project.repo_root, settings, locations))
    for extra in project.additional_dirs:
        if not _resolve(extra, locations).is_dir():
            findings.append(Finding(GROUP, Severity.WARNING, f"{name}: additional dir does not exist: {extra}."))
    if project.working_style and project.working_style not in styles:
        findings.append(Finding(GROUP, Severity.WARNING, f"{name}: working_style '{project.working_style}' not found."))
    if project.context and project.context not in contexts:
        findings.append(Finding(GROUP, Severity.WARNING, f"{name}: context '{project.context}' not found."))
    return findings


def _check_repo_root(name: str, repo_root: str, locations: Locations) -> list[Finding]:
    resolved = _resolve(repo_root, locations)
    if not resolved.exists():
        return [Finding(GROUP, Severity.ERROR, f"{name}: repo_root does not exist: {resolved}.")]
    if not resolved.is_dir():
        return [Finding(GROUP, Severity.ERROR, f"{name}: repo_root is not a directory: {resolved}.")]
    if not (resolved / ".git").exists():
        return [Finding(GROUP, Severity.WARNING, f"{name}: repo_root is not a git repository: {resolved}.")]
    return []


def _check_repo_root_storage(name: str, repo_root: str, settings: Settings, locations: Locations) -> list[Finding]:
    """Flag a repo_root stored as an absolute path under $HOME (fixable → home-relative).

    The porcelain always stores repo roots home-relative; an absolute one only
    arises from a hand-edited config, and ``--fix`` can normalize it losslessly.
    """
    candidate = Path(repo_root)
    if not candidate.is_absolute():
        return []
    try:
        candidate.relative_to(locations.home)
    except ValueError:
        return []  # absolute but outside $HOME — cannot be stored home-relative
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            f"{name}: repo_root is stored as an absolute path under $HOME (should be home-relative).",
            remedy=Remedy.FIX,
            action=f"relativize {name} repo_root",
            apply=lambda: repair.relativize_repo_root(settings, name, locations.home),
        )
    ]


def _resolve(stored: str, locations: Locations) -> Path:
    candidate = Path(stored)
    return candidate if candidate.is_absolute() else locations.home / candidate


def _available_styles(settings: Settings, locations: Locations) -> set[str]:
    styles: set[str] = set()
    install_dir = settings.install_dir
    if install_dir:
        bundled = Path(install_dir) / "pi" / "system-prompt" / "defaults" / "styles"
        if bundled.is_dir():
            styles.update(path.stem for path in bundled.glob("*.md"))
    if locations.styles_dir.is_dir():
        styles.update(path.stem for path in locations.styles_dir.glob("*.md"))
    return styles


def _available_contexts(locations: Locations) -> set[str]:
    if not locations.context_dir.is_dir():
        return set()
    return {path.stem for path in locations.context_dir.glob("*.md")}
