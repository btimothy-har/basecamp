"""Tests for the standalone Basecamp local-state migration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_migration() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "migrations" / "001_consolidate_basecamp_state.py"
    spec = importlib.util.spec_from_file_location("consolidate_basecamp_state", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_dry_run_does_not_write_targets(tmp_path: Path) -> None:
    migration = _load_migration()
    _write(tmp_path / ".pi" / "context" / "demo.md", "legacy context")

    actions = migration.run(migration.MigrationOptions(home=tmp_path))

    assert any(action.kind == "copy" for action in actions)
    assert not (tmp_path / ".pi" / "basecamp" / "workspace" / "context" / "demo.md").exists()


def test_apply_copies_legacy_state_to_bounded_contexts(tmp_path: Path) -> None:
    migration = _load_migration()
    _write(tmp_path / ".pi" / "context" / "demo.md", "context")
    _write(tmp_path / ".pi" / "styles" / "engineering.md", "style")
    _write(tmp_path / ".pi" / "prompts" / "environment.md", "prompt")
    _write(tmp_path / ".pi" / "session-state" / "session.json", "state")
    _write(tmp_path / ".pi" / "model-aliases" / "config.json", '{"version":0,"aliases":{" fast ":" provider/model "}}')
    _write(tmp_path / ".pi" / "tasks" / "session.json", "[]")
    _write(tmp_path / ".pi" / "agent" / "basecamp" / "daemon.db", "db")
    _write(tmp_path / ".pi" / "agent" / "basecamp" / "agents" / "agent-1" / "log.json", "agent")

    migration.run(migration.MigrationOptions(home=tmp_path, apply=True))

    root = tmp_path / ".pi" / "basecamp"
    assert (root / "workspace" / "context" / "demo.md").read_text(encoding="utf-8") == "context"
    assert (root / "workspace" / "styles" / "engineering.md").read_text(encoding="utf-8") == "style"
    assert (root / "workspace" / "prompts" / "environment.md").read_text(encoding="utf-8") == "prompt"
    assert (root / "core" / "session-state" / "session.json").read_text(encoding="utf-8") == "state"
    assert json.loads((root / "core" / "model-aliases.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "aliases": {"fast": "provider/model"},
    }
    assert (root / "tasks" / "session.json").read_text(encoding="utf-8") == "[]"
    assert (root / "swarm" / "daemon.db").read_text(encoding="utf-8") == "db"
    assert (root / "swarm" / "agents" / "agent-1" / "log.json").read_text(encoding="utf-8") == "agent"
    assert not (root / "swarm" / "daemon.pid").exists()


def test_apply_skips_swarm_state_when_runtime_artifacts_exist(tmp_path: Path) -> None:
    migration = _load_migration()
    _write(tmp_path / ".pi" / "agent" / "basecamp" / "daemon.db", "db")
    _write(tmp_path / ".pi" / "agent" / "basecamp" / "agents" / "agent-1" / "log.json", "agent")
    _write(tmp_path / ".pi" / "agent" / "basecamp" / "daemon.pid", "123\n")

    actions = migration.run(migration.MigrationOptions(home=tmp_path, apply=True))

    root = tmp_path / ".pi" / "basecamp"
    assert not (root / "swarm" / "daemon.db").exists()
    assert not (root / "swarm" / "agents" / "agent-1" / "log.json").exists()
    assert any(action.kind == "runtime-skip" and action.source.name == "daemon.pid" for action in actions)
    assert any(action.kind == "skip" and action.source == tmp_path / ".pi" / "agent" / "basecamp" for action in actions)


def test_apply_extracts_projects_and_strips_root_config(tmp_path: Path) -> None:
    migration = _load_migration()
    root_config = tmp_path / ".pi" / "basecamp" / "config.json"
    _write(
        root_config,
        '{"install_dir":"/repo","projects":{"demo":{"repo_root":"repo"}},"models":{"fast":"provider/model"},"worktree_branch_prefix":"bh/","observer":{"mode":"off"}}',
    )

    migration.run(migration.MigrationOptions(home=tmp_path, apply=True))

    projects = root_config.parent / "workspace" / "projects.json"
    aliases = root_config.parent / "core" / "model-aliases.json"
    assert json.loads(projects.read_text(encoding="utf-8")) == {
        "version": 1,
        "projects": {"demo": {"repo_root": "repo"}},
    }
    assert json.loads(aliases.read_text(encoding="utf-8")) == {
        "version": 1,
        "aliases": {"fast": "provider/model"},
    }
    assert json.loads(root_config.read_text(encoding="utf-8")) == {"install_dir": "/repo", "version": 1}


def test_dry_run_does_not_duplicate_planned_model_alias_target(tmp_path: Path) -> None:
    migration = _load_migration()
    root_config = tmp_path / ".pi" / "basecamp" / "config.json"
    aliases = root_config.parent / "core" / "model-aliases.json"
    _write(root_config, '{"models":{"fast":"provider/model"}}')
    _write(tmp_path / ".pi" / "model-aliases" / "config.json", '{"aliases":{"slow":"provider/slow"}}')

    actions = migration.run(migration.MigrationOptions(home=tmp_path))

    writes_to_aliases = [action for action in actions if action.kind in {"copy", "update"} and action.target == aliases]
    assert len(writes_to_aliases) == 1
    assert any(
        action.kind == "skip"
        and action.source == tmp_path / ".pi" / "model-aliases" / "config.json"
        and action.target == aliases
        for action in actions
    )


def test_apply_retains_root_projects_and_models_when_targets_exist(tmp_path: Path) -> None:
    migration = _load_migration()
    root_config = tmp_path / ".pi" / "basecamp" / "config.json"
    projects = root_config.parent / "workspace" / "projects.json"
    aliases = root_config.parent / "core" / "model-aliases.json"
    _write(
        root_config,
        '{"install_dir":"/repo","projects":{"demo":{"repo_root":"repo"}},"models":{"fast":"provider/model"},"observer":{"mode":"off"}}',
    )
    _write(projects, '{"version":1,"projects":{"existing":{"repo_root":"existing"}}}')
    _write(aliases, '{"version":1,"aliases":{"existing":"provider/existing"}}')

    migration.run(migration.MigrationOptions(home=tmp_path, apply=True))

    assert json.loads(root_config.read_text(encoding="utf-8")) == {
        "install_dir": "/repo",
        "projects": {"demo": {"repo_root": "repo"}},
        "models": {"fast": "provider/model"},
        "version": 1,
    }


def test_apply_does_not_overwrite_existing_targets(tmp_path: Path) -> None:
    migration = _load_migration()
    source = tmp_path / ".pi" / "model-aliases" / "config.json"
    target = tmp_path / ".pi" / "basecamp" / "core" / "model-aliases.json"
    _write(source, "legacy")
    _write(target, "new")

    actions = migration.run(migration.MigrationOptions(home=tmp_path, apply=True))

    assert target.read_text(encoding="utf-8") == "new"
    assert any(action.kind == "skip" and action.source == source and action.target == target for action in actions)


def test_prune_empty_only_removes_empty_legacy_dirs(tmp_path: Path) -> None:
    migration = _load_migration()
    empty_context = tmp_path / ".pi" / "context"
    non_empty_styles = tmp_path / ".pi" / "styles"
    empty_context.mkdir(parents=True)
    _write(non_empty_styles / "style.md", "style")

    migration.run(migration.MigrationOptions(home=tmp_path, apply=True, prune_empty=True))

    assert not empty_context.exists()
    assert non_empty_styles.exists()
