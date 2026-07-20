"""End-to-end doctor repair composition."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import basecamp.doctor.hub as hub
import basecamp.doctor.retired as retired
from basecamp.doctor.models import DoctorPaths
from basecamp.doctor.process import DaemonState, DaemonStatus
from basecamp.doctor.service import run_doctor


def test_one_repair_pass_uses_one_recovery_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    paths.config.parent.mkdir(parents=True)
    paths.config.write_text('{"version": 0, "models": {"fast": "model"}}\n', encoding="utf-8")
    paths.config.chmod(0o600)
    legacy_context = paths.legacy_context / "project.md"
    legacy_context.parent.mkdir(parents=True)
    legacy_context.write_text("context\n", encoding="utf-8")
    launch_index = paths.workstream_launches / "launch-index.json"
    launch_index.parent.mkdir(parents=True)
    launch_index.write_text("{}\n", encoding="utf-8")
    paths.swarm.mkdir(parents=True)
    with sqlite3.connect(paths.daemon_db) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY, parent_id TEXT, sibling_group TEXT, depth INTEGER, role TEXT,
                session_name TEXT, cwd TEXT, created_at TEXT, last_seen_at TEXT, agent_handle TEXT
            )
            """
        )

    def down(*_args, **_kwargs) -> DaemonStatus:
        return DaemonStatus(DaemonState.DOWN)

    monkeypatch.setattr(hub, "inspect_daemon", down)
    monkeypatch.setattr(retired, "inspect_daemon", down)

    checked = run_doctor(paths)
    repaired = run_doctor(paths, repair=True)
    final = run_doctor(paths)

    assert checked.exit_code == 1
    assert repaired.exit_code == 0
    assert final.exit_code == 0
    assert repaired.archive_path is not None
    manifest = json.loads((repaired.archive_path / "manifest.json").read_text(encoding="utf-8"))
    destinations = {entry["destination"] for entry in manifest["entries"]}
    assert destinations == {
        "backups/config.json",
        "backups/swarm/daemon.db",
        "retired/workspace/context",
        "retired/workstream-launches",
    }
    assert not paths.legacy_context.exists()
    assert not paths.workstream_launches.exists()
    assert paths.context.joinpath("project.md").read_text(encoding="utf-8") == "context\n"
