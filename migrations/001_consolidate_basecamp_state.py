#!/usr/bin/env python3
"""Consolidate Basecamp-owned local state under ~/.pi/basecamp.

Dry-run is the default:

    python migrations/001_consolidate_basecamp_state.py

Apply copies with:

    python migrations/001_consolidate_basecamp_state.py --apply

The migration copies legacy files into the new bounded-context layout when the
new target is missing, extracts root config-owned workspace/core data into their
bounded-context files, and leaves legacy directories in place unless explicitly
pruned. Runtime-only daemon artifacts such as sockets, PID files, and spawn
locks are reported but not copied.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ActionKind = Literal[
    "copy",
    "ensure-dir",
    "missing",
    "prune-empty",
    "retain-non-empty",
    "runtime-skip",
    "skip",
    "update",
]


@dataclass(frozen=True)
class MigrationOptions:
    """Runtime options for the local-state migration."""

    home: Path
    apply: bool = False
    prune_empty: bool = False


@dataclass(frozen=True)
class Action:
    """One planned or applied migration action."""

    kind: ActionKind
    source: Path | None
    target: Path | None
    detail: str


def pi_dir(home: Path) -> Path:
    """Return the Pi root for a home directory."""

    return home / ".pi"


def basecamp_dir(home: Path) -> Path:
    """Return the Basecamp root for a home directory."""

    return pi_dir(home) / "basecamp"


def _is_regular_file(path: Path) -> bool:
    """Return whether path is a regular non-symlink file."""

    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def _path_label(path: Path | None, home: Path) -> str:
    """Format a path for human-readable output."""

    if path is None:
        return "—"
    try:
        relative = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if str(relative) == "." else f"~/{relative}"


def _record(
    actions: list[Action],
    kind: ActionKind,
    source: Path | None,
    target: Path | None,
    detail: str,
) -> None:
    actions.append(Action(kind=kind, source=source, target=target, detail=detail))


def _ensure_dir(path: Path, options: MigrationOptions, actions: list[Action]) -> None:
    if path.exists() or any(action.kind == "ensure-dir" and action.target == path for action in actions):
        return
    _record(actions, "ensure-dir", None, path, "create target directory")
    if options.apply:
        path.mkdir(parents=True, exist_ok=True)


def _copy_regular_file(source: Path, target: Path, options: MigrationOptions, actions: list[Action]) -> None:
    if not source.exists():
        _record(actions, "missing", source, target, "legacy source is absent")
        return
    if not _is_regular_file(source):
        _record(actions, "skip", source, target, "source is not a regular file")
        return
    if target.exists():
        _record(actions, "skip", source, target, "target already exists")
        return

    _record(actions, "copy", source, target, "copy file")
    if options.apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_directory_tree(source: Path, target: Path, options: MigrationOptions, actions: list[Action]) -> None:
    if not source.exists():
        _record(actions, "missing", source, target, "legacy source directory is absent")
        return
    if not source.is_dir() or source.is_symlink():
        _record(actions, "skip", source, target, "source is not a regular directory")
        return

    _ensure_dir(target, options, actions)
    for root, dirs, files in os.walk(source):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
        relative_root = root_path.relative_to(source)
        target_root = target / relative_root
        _ensure_dir(target_root, options, actions)

        for name in sorted(files):
            _copy_regular_file(root_path / name, target_root / name, options, actions)


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _write_json_object(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
    path.chmod(0o600)


def _string_map(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            return None
        stripped_key = key.strip()
        stripped_item = item.strip()
        if not stripped_key or not stripped_item:
            return None
        result[stripped_key] = stripped_item
    return result


def _migrate_root_config(home: Path, options: MigrationOptions, actions: list[Action]) -> None:
    root_config_path = basecamp_dir(home) / "config.json"
    projects_path = basecamp_dir(home) / "workspace" / "projects.json"
    aliases_path = basecamp_dir(home) / "core" / "model-aliases.json"
    data = _read_json_object(root_config_path)
    if data is None:
        _record(actions, "missing", root_config_path, None, "root config is absent or not a JSON object")
        return

    projects = data.get("projects")
    if isinstance(projects, dict):
        if projects_path.exists():
            _record(actions, "skip", root_config_path, projects_path, "workspace projects file already exists")
        else:
            _record(actions, "copy", root_config_path, projects_path, "extract projects to workspace projects file")
            if options.apply:
                _write_json_object(projects_path, {"version": 1, "projects": projects})

    models = _string_map(data.get("models"))
    if models is not None:
        if aliases_path.exists():
            _record(actions, "skip", root_config_path, aliases_path, "core model aliases file already exists")
        else:
            _record(actions, "copy", root_config_path, aliases_path, "extract model aliases to core alias file")
            if options.apply:
                _write_json_object(aliases_path, {"version": 1, "aliases": models})

    cleanup_keys = ("projects", "models", "worktree_branch_prefix", "observer")
    cleaned = dict(data)
    for key in cleanup_keys:
        cleaned.pop(key, None)
    if "install_dir" in cleaned:
        cleaned.setdefault("version", 1)

    if cleaned != data:
        _record(actions, "update", root_config_path, None, "remove workspace/core/stale keys from root config")
        if options.apply:
            _write_json_object(root_config_path, cleaned)


def _migrate_companion(home: Path, options: MigrationOptions, actions: list[Action]) -> None:
    source_dir = pi_dir(home) / "companion"
    snapshots_dir = basecamp_dir(home) / "companion" / "snapshots"
    analysis_dir = basecamp_dir(home) / "companion" / "analysis"

    _ensure_dir(snapshots_dir, options, actions)
    _ensure_dir(analysis_dir, options, actions)

    if not source_dir.exists():
        _record(actions, "missing", source_dir, snapshots_dir.parent, "legacy companion directory is absent")
        return
    if not source_dir.is_dir() or source_dir.is_symlink():
        _record(actions, "skip", source_dir, snapshots_dir.parent, "legacy companion path is not a directory")
        return

    for source in sorted(source_dir.iterdir()):
        if source.name.endswith(".analysis.json"):
            target = analysis_dir / source.name
        elif source.suffix == ".json":
            target = snapshots_dir / source.name
        else:
            _record(actions, "skip", source, None, "not a companion JSON snapshot or analysis sidecar")
            continue
        _copy_regular_file(source, target, options, actions)


def _migrate_swarm(home: Path, options: MigrationOptions, actions: list[Action]) -> None:
    legacy_dir = pi_dir(home) / "agent" / "basecamp"
    swarm_dir = basecamp_dir(home) / "swarm"

    _ensure_dir(swarm_dir, options, actions)
    _copy_regular_file(legacy_dir / "daemon.db", swarm_dir / "daemon.db", options, actions)
    _copy_directory_tree(legacy_dir / "agents", swarm_dir / "agents", options, actions)

    for name in ("daemon.sock", "daemon.pid", "daemon.spawn.lock"):
        runtime_path = legacy_dir / name
        if runtime_path.exists():
            _record(actions, "runtime-skip", runtime_path, swarm_dir / name, "runtime artifact is not copied")


def _prune_empty_legacy_dirs(home: Path, options: MigrationOptions, actions: list[Action]) -> None:
    if not options.prune_empty:
        return

    legacy_dirs = [
        pi_dir(home) / "context",
        pi_dir(home) / "styles",
        pi_dir(home) / "prompts",
        pi_dir(home) / "session-state",
        pi_dir(home) / "model-aliases",
        pi_dir(home) / "tasks",
        pi_dir(home) / "companion",
        pi_dir(home) / "agent" / "basecamp",
    ]

    for legacy_dir in sorted(legacy_dirs, key=lambda path: len(path.parts), reverse=True):
        if not legacy_dir.exists() or not legacy_dir.is_dir() or legacy_dir.is_symlink():
            continue
        try:
            is_empty = next(legacy_dir.iterdir(), None) is None
        except OSError:
            _record(actions, "skip", legacy_dir, None, "could not inspect legacy directory")
            continue

        if not is_empty:
            _record(actions, "retain-non-empty", legacy_dir, None, "legacy directory is non-empty; leaving as backup")
            continue

        _record(actions, "prune-empty", legacy_dir, None, "remove empty legacy directory")
        if options.apply:
            legacy_dir.rmdir()


def run(options: MigrationOptions) -> list[Action]:
    """Plan or apply the Basecamp local-state migration."""

    home = options.home.expanduser()
    actions: list[Action] = []
    target_basecamp = basecamp_dir(home)

    for target_dir in (
        target_basecamp,
        target_basecamp / "workspace",
        target_basecamp / "workspace" / "context",
        target_basecamp / "workspace" / "styles",
        target_basecamp / "workspace" / "prompts",
        target_basecamp / "core",
        target_basecamp / "core" / "session-state",
        target_basecamp / "tasks",
    ):
        _ensure_dir(target_dir, options, actions)

    _migrate_root_config(home, options, actions)
    _copy_directory_tree(pi_dir(home) / "context", target_basecamp / "workspace" / "context", options, actions)
    _copy_directory_tree(pi_dir(home) / "styles", target_basecamp / "workspace" / "styles", options, actions)
    _copy_directory_tree(pi_dir(home) / "prompts", target_basecamp / "workspace" / "prompts", options, actions)
    _copy_directory_tree(pi_dir(home) / "session-state", target_basecamp / "core" / "session-state", options, actions)
    _copy_regular_file(
        pi_dir(home) / "model-aliases" / "config.json",
        target_basecamp / "core" / "model-aliases.json",
        options,
        actions,
    )
    _copy_directory_tree(pi_dir(home) / "tasks", target_basecamp / "tasks", options, actions)
    _migrate_companion(home, options, actions)
    _migrate_swarm(home, options, actions)
    _prune_empty_legacy_dirs(home, options, actions)

    return actions


def emit_report(actions: list[Action], options: MigrationOptions) -> None:
    """Print a migration report."""

    mode = "APPLY" if options.apply else "DRY RUN"
    print(f"Basecamp local-state consolidation ({mode})")
    if not options.apply:
        print("No changes were written. Re-run with --apply to copy missing targets.")
    if options.prune_empty and not options.apply:
        print("Empty legacy directories are only reported; add --apply to remove them.")
    print()

    if not actions:
        print("No actions needed.")
        return

    for action in actions:
        source = _path_label(action.source, options.home.expanduser())
        target = _path_label(action.target, options.home.expanduser())
        if action.target is None:
            print(f"[{action.kind}] {source} — {action.detail}")
        elif action.source is None:
            print(f"[{action.kind}] {target} — {action.detail}")
        else:
            print(f"[{action.kind}] {source} -> {target} — {action.detail}")

    counts: dict[str, int] = {}
    for action in actions:
        counts[action.kind] = counts.get(action.kind, 0) + 1
    summary = ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
    print()
    print(f"Summary: {summary}")


def parse_args(argv: list[str]) -> MigrationOptions:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="copy missing targets instead of dry-running")
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="home directory to migrate (default: current user's home)",
    )
    parser.add_argument(
        "--prune-empty",
        action="store_true",
        help="remove legacy directories that are already empty after planning/apply",
    )
    args = parser.parse_args(argv)
    return MigrationOptions(home=args.home, apply=args.apply, prune_empty=args.prune_empty)


def main(argv: list[str] | None = None) -> int:
    """Run the migration CLI."""

    options = parse_args(sys.argv[1:] if argv is None else argv)
    actions = run(options)
    emit_report(actions, options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
