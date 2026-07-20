"""Lossless, mechanical config repairs applied under ``basecamp doctor --fix``.

Every function here is safe to run unattended: it either writes a value whose
correct form is unambiguous (``version``) or removes config that is already
dead — ignored by the read path or carrying no information. Nothing that needs
human judgement (an unknown key, a repo root that points nowhere) lives here;
those are reported, never auto-repaired. All writes go through the same flock'd
:class:`~basecamp.core.settings.Settings` writer the rest of basecamp uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from basecamp.core.model_aliases import MODEL_ALIASES_SECTION, load_model_aliases
from basecamp.core.projects import PROJECTS_SECTION
from basecamp.core.settings import CONFIG_VERSION, Settings


def set_version(settings: Settings) -> None:
    """Stamp the current config version onto the document."""

    def mutate(data: dict[str, Any]) -> None:
        data["version"] = CONFIG_VERSION

    settings.update(mutate)


def drop_top_level_key(settings: Settings, key: str) -> None:
    """Remove a dead top-level key (e.g. the retired ``installed_modules``)."""

    def mutate(data: dict[str, Any]) -> None:
        data.pop(key, None)
        data["version"] = CONFIG_VERSION

    settings.update(mutate)


def prune_malformed_aliases(settings: Settings) -> None:
    """Rewrite ``model_aliases`` to only the entries the read path already keeps.

    :func:`~basecamp.core.model_aliases.load_model_aliases` drops non-string and
    blank entries leniently; persisting its result makes the on-disk section
    match what basecamp already uses, discarding nothing that was in effect.
    """
    kept = load_model_aliases(settings)

    def mutate(data: dict[str, Any]) -> None:
        data[MODEL_ALIASES_SECTION] = dict(kept)
        data["version"] = CONFIG_VERSION

    settings.update(mutate)


def drop_record(settings: Settings, section: str, key: str) -> None:
    """Remove one record from a ``{name: record}`` section (e.g. an empty environment).

    ``section`` is sourced from the config registry by the caller, so core does
    not need to import the domain that owns the section.
    """

    def mutate(data: dict[str, Any]) -> None:
        records = data.get(section)
        if isinstance(records, dict) and key in records:
            records = dict(records)
            records.pop(key, None)
            data[section] = records
            data["version"] = CONFIG_VERSION

    settings.update(mutate)


def relativize_repo_root(settings: Settings, project: str, home: Path) -> None:
    """Rewrite an absolute-but-under-``$HOME`` repo root to its home-relative form."""

    def mutate(data: dict[str, Any]) -> None:
        projects = data.get(PROJECTS_SECTION)
        if not isinstance(projects, dict):
            return
        record = projects.get(project)
        if not isinstance(record, dict):
            return
        raw = record.get("repo_root")
        if not isinstance(raw, str):
            return
        candidate = Path(raw)
        if not candidate.is_absolute():
            return
        try:
            relative = candidate.relative_to(home)
        except ValueError:
            return
        record = {**record, "repo_root": str(relative)}
        projects = {**projects, project: record}
        data[PROJECTS_SECTION] = projects
        data["version"] = CONFIG_VERSION

    settings.update(mutate)


def scaffold_dirs(paths: tuple[Path, ...]) -> None:
    """Create any missing user-override directories."""
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
