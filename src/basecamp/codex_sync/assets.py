# ruff: noqa: E501
"""Codex projection assets installed by the sync command."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import tomlkit
from basecamp_core.settings import settings
from tomlkit.exceptions import TOMLKitError

_CODEX_ASSET_DIR = "codex"
_PROJECTION_MANIFEST = "projection.toml"


class CodexAssetError(Exception):
    """Raised when bundled Codex projection assets are invalid."""


class CodexAssetNotFoundError(CodexAssetError, FileNotFoundError):
    """Raised when a bundled Codex projection asset cannot be found."""

    def __init__(self, parts: tuple[str, ...]) -> None:
        super().__init__(f"Unable to find Codex asset: {_CODEX_ASSET_DIR}/{'/'.join(parts)}")


class InvalidCodexAssetError(CodexAssetError):
    """Raised when a bundled Codex projection asset has an unsupported shape."""


class InvalidCodexAssetReferenceError(InvalidCodexAssetError):
    """Raised when a manifest asset reference is unsafe or unsupported."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"Invalid Codex asset reference: {ref}")


class InvalidCodexAssetTomlError(InvalidCodexAssetError):
    """Raised when a TOML asset cannot be parsed."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"Invalid TOML in Codex asset: {ref}")


class CodexAssetTableError(InvalidCodexAssetError):
    """Raised when a TOML asset or section is not a table."""

    def __init__(self, owner: str, name: str | None = None) -> None:
        target = f"[{name}] table in {owner}" if name else f"TOML table: {owner}"
        super().__init__(f"Missing or invalid Codex asset {target}")


class CodexAssetStringError(InvalidCodexAssetError):
    """Raised when a required string field is missing."""

    def __init__(self, owner: str, key: str) -> None:
        super().__init__(f"Missing string value {key!r} in {owner}")


class CodexAssetStringListError(InvalidCodexAssetError):
    """Raised when a required string list field is missing."""

    def __init__(self, owner: str, key: str) -> None:
        super().__init__(f"Missing string list {key!r} in {owner}")


class CodexAssetTableListError(InvalidCodexAssetError):
    """Raised when a required table list field is missing."""

    def __init__(self, owner: str, key: str) -> None:
        super().__init__(f"Missing table list {key!r} in {owner}")


class CodexSkillInstallModeError(InvalidCodexAssetError):
    """Raised when a skill declares an unsupported install mode."""

    def __init__(self, owner: str, mode: str) -> None:
        super().__init__(f"Unsupported skill install mode {mode!r} in {owner}")


def _repo_root_asset_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[3].joinpath(_CODEX_ASSET_DIR, *parts)


def _packaged_asset_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[1].joinpath(_CODEX_ASSET_DIR, *parts)


def _read_codex_asset(*parts: str) -> str:
    for path in _codex_asset_paths(*parts):
        if path.exists():
            return path.read_text()
    raise CodexAssetNotFoundError(parts)


def _codex_asset_paths(*parts: str) -> tuple[Path, Path]:
    return (_repo_root_asset_path(*parts), _packaged_asset_path(*parts))


def _resolve_codex_asset_path(*parts: str) -> Path:
    for path in _codex_asset_paths(*parts):
        if path.exists():
            return path
    raise CodexAssetNotFoundError(parts)


def _repo_source_paths(*parts: str) -> tuple[Path, ...]:
    paths: list[Path] = []
    if settings.install_dir:
        paths.append(Path(settings.install_dir).joinpath(*parts))
    paths.append(Path(__file__).resolve().parents[3].joinpath(*parts))
    return tuple(paths)


def resolve_projection_source(ref: str) -> Path:
    """Resolve a manifest source reference to a local directory or file."""
    parts = _asset_ref_parts(ref)
    if parts[0] == _CODEX_ASSET_DIR:
        return _resolve_codex_asset_path(*parts[1:])

    for path in _repo_source_paths(*parts):
        if path.exists():
            return path
    raise CodexAssetNotFoundError(parts)


def _asset_ref_parts(ref: str) -> tuple[str, ...]:
    path = PurePosixPath(ref)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise InvalidCodexAssetReferenceError(ref)
    return path.parts


def _read_asset_ref(ref: str) -> str:
    return _read_codex_asset(*_asset_ref_parts(ref))


def _parse_toml_asset(ref: str) -> Mapping[str, Any]:
    try:
        parsed = tomlkit.parse(_read_asset_ref(ref))
    except TOMLKitError as error:
        raise InvalidCodexAssetTomlError(ref) from error

    if not isinstance(parsed, Mapping):
        raise CodexAssetTableError(ref)
    return parsed


def _load_projection() -> Mapping[str, Any]:
    return _parse_toml_asset(_PROJECTION_MANIFEST)


def _section(document: Mapping[str, Any], name: str, owner: str) -> Mapping[str, Any]:
    value = document.get(name)
    if not isinstance(value, Mapping):
        raise CodexAssetTableError(owner, name)
    return value


def _string(table: Mapping[str, Any], key: str, owner: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CodexAssetStringError(owner, key)
    return value


def _string_list(table: Mapping[str, Any], key: str, owner: str) -> list[str]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise CodexAssetStringListError(owner, key)
    return value


def _table_list(table: Mapping[str, Any], key: str, owner: str) -> list[Mapping[str, Any]]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise CodexAssetTableListError(owner, key)
    return value


@dataclass(frozen=True)
class AgentDefinition:
    """A Codex standalone agent definition."""

    filename: str
    name: str
    description: str
    developer_instructions: str


@dataclass(frozen=True)
class SkillDefinition:
    """A Codex skill directory declared by the projection manifest."""

    name: str
    source_ref: str
    install_mode: str

    @property
    def source_dir(self) -> Path:
        """Resolve the source directory lazily for installers and tests."""
        return resolve_projection_source(self.source_ref)


def _load_agent(ref: str) -> AgentDefinition:
    document = _parse_toml_asset(ref)
    return AgentDefinition(
        filename=PurePosixPath(ref).name,
        name=_string(document, "name", ref),
        description=_string(document, "description", ref),
        developer_instructions=_string(document, "developer_instructions", ref),
    )


def _load_agents(projection: Mapping[str, Any]) -> list[AgentDefinition]:
    agents = _section(projection, "agents", _PROJECTION_MANIFEST)
    return [_load_agent(ref) for ref in _string_list(agents, "files", f"{_PROJECTION_MANIFEST} [agents]")]


def _load_skill(entry: Mapping[str, Any], owner: str) -> SkillDefinition:
    name = _string(entry, "name", owner)
    source_ref = _string(entry, "source", owner)
    install_mode = _string(entry, "install", owner)
    if install_mode not in {"copy", "symlink"}:
        raise CodexSkillInstallModeError(owner, install_mode)
    return SkillDefinition(name=name, source_ref=source_ref, install_mode=install_mode)


def _load_skills(projection: Mapping[str, Any]) -> list[SkillDefinition]:
    skills = _section(projection, "skills", _PROJECTION_MANIFEST)
    owner = f"{_PROJECTION_MANIFEST} [skills]"
    return [_load_skill(entry, owner) for entry in _table_list(skills, "directories", owner)]


PROJECTION = _load_projection()

_instructions = _section(PROJECTION, "instructions", _PROJECTION_MANIFEST)
OPERATING_GUIDELINES = _read_asset_ref(_string(_instructions, "developer_instructions", f"{_PROJECTION_MANIFEST} [instructions]")).strip()

AGENTS = _load_agents(PROJECTION)
SKILLS = _load_skills(PROJECTION)
