"""Hub database diagnosis and offline canonical migration."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

import basecamp.doctor.hub as hub
from basecamp.doctor.archive import DoctorArchive
from basecamp.doctor.hub import inspect_hub, repair_hub
from basecamp.doctor.models import DoctorPaths, Severity
from basecamp.doctor.process import DaemonState, DaemonStatus
from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.store import Store
from basecamp.hub.store.contract import REQUIRED_COLUMNS, STORE_USER_VERSION


@pytest.fixture(autouse=True)
def daemon_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hub, "inspect_daemon", lambda *_args, **_kwargs: DaemonStatus(DaemonState.DOWN))


def _paths(tmp_path: Path) -> DoctorPaths:
    paths = DoctorPaths.for_home(tmp_path)
    paths.swarm.mkdir(parents=True)
    return paths


def _checks(report) -> dict[str, Severity]:
    return {check.identifier: check.severity for check in report.checks}


def _legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                agent_handle TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agents (
                id, parent_id, sibling_group, depth, role, session_name, cwd, created_at, last_seen_at, agent_handle
            ) VALUES ('legacy', NULL, NULL, 0, 'session', 'legacy', '/tmp', 'created', 'seen', NULL)
            """
        )


def test_missing_database_is_not_an_error(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    report = inspect_hub(paths)

    assert report.exit_code == 0
    assert _checks(report)["database.missing"] is Severity.INFO


def test_healthy_store_check_is_read_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    Store(db_path=paths.daemon_db, task_dir=paths.root / "tasks")
    before = paths.daemon_db.read_bytes()

    report = inspect_hub(paths)

    assert report.exit_code == 0
    assert _checks(report)["database.integrity"] is Severity.PASS
    assert _checks(report)["database.schema"] is Severity.PASS
    assert _checks(report)["database.invariants"] is Severity.PASS
    assert paths.daemon_db.read_bytes() == before
    assert not paths.archive_root.exists()


def test_offline_legacy_store_is_backed_up_and_migrated(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _legacy_database(paths.daemon_db)
    checked = inspect_hub(paths)
    archive = DoctorArchive(paths, timestamp="stamp")

    errors = repair_hub(paths, archive)
    final = inspect_hub(paths)

    assert checked.exit_code == 1
    assert _checks(checked)["database.schema"] is Severity.REPAIRABLE
    assert errors == []
    assert final.exit_code == 0
    assert archive.path is not None
    backup = archive.path / "backups" / "swarm" / "daemon.db"
    assert backup.exists()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    with sqlite3.connect(backup) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == {
            "agents"
        }
    with sqlite3.connect(paths.daemon_db) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == STORE_USER_VERSION
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        handle = connection.execute("SELECT agent_handle FROM agents WHERE id = 'legacy'").fetchone()[0]
    assert REQUIRED_COLUMNS.keys() <= tables
    assert handle == "legacy"

    second_archive = DoctorArchive(paths, timestamp="second")
    assert repair_hub(paths, second_archive) == []
    assert second_archive.path is None


def test_live_or_ambiguous_daemon_blocks_pending_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for state in (DaemonState.LIVE, DaemonState.AMBIGUOUS):
        home = tmp_path / state.value
        paths = _paths(home)
        _legacy_database(paths.daemon_db)
        protocol = PROTOCOL_VERSION if state is DaemonState.LIVE else None
        monkeypatch.setattr(
            hub,
            "inspect_daemon",
            lambda *_args, _state=state, _protocol=protocol, **_kwargs: DaemonStatus(_state, protocol=_protocol),
        )
        before = paths.daemon_db.read_bytes()
        archive = DoctorArchive(paths, timestamp="stamp")

        errors = repair_hub(paths, archive)

        assert len(errors) == 1
        assert errors[0].severity is Severity.ERROR
        assert paths.daemon_db.read_bytes() == before
        assert archive.path is None


def test_liveness_race_inside_spawn_lock_aborts_without_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    _legacy_database(paths.daemon_db)
    statuses = iter(
        [
            DaemonStatus(DaemonState.DOWN),
            DaemonStatus(DaemonState.LIVE, protocol=PROTOCOL_VERSION),
        ]
    )
    monkeypatch.setattr(hub, "inspect_daemon", lambda *_args, **_kwargs: next(statuses))
    before = paths.daemon_db.read_bytes()
    archive = DoctorArchive(paths, timestamp="stamp")

    errors = repair_hub(paths, archive)

    assert [error.identifier for error in errors] == ["database.repair_race"]
    assert paths.daemon_db.read_bytes() == before
    assert not paths.daemon_spawn_lock.exists()
    assert archive.path is None


def test_spawn_lock_contention_aborts_without_replacing_owner(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _legacy_database(paths.daemon_db)
    owner = b'{"pid": 999, "ts": 1}'
    paths.daemon_spawn_lock.write_bytes(owner)
    before = paths.daemon_db.read_bytes()
    archive = DoctorArchive(paths, timestamp="stamp")

    errors = repair_hub(paths, archive)

    assert [error.identifier for error in errors] == ["database.repair_spawn_lock"]
    assert paths.daemon_db.read_bytes() == before
    assert paths.daemon_spawn_lock.read_bytes() == owner
    assert archive.path is None


def test_failed_database_backup_removes_partial_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    _legacy_database(paths.daemon_db)
    before = paths.daemon_db.read_bytes()
    archive = DoctorArchive(paths, timestamp="stamp")

    def reject_backup(_connection: sqlite3.Connection) -> None:
        raise sqlite3.DatabaseError

    monkeypatch.setattr(hub, "_require_valid_backup", reject_backup)

    errors = repair_hub(paths, archive)

    assert [error.identifier for error in errors] == ["database.repair_failed"]
    assert paths.daemon_db.read_bytes() == before
    assert archive.path is not None
    assert not (archive.path / "backups" / "swarm" / "daemon.db").exists()
    archive.discard_if_empty()
    assert archive.path is None


def test_corrupt_and_forward_database_are_report_only(tmp_path: Path) -> None:
    corrupt_paths = _paths(tmp_path / "corrupt")
    corrupt_paths.daemon_db.write_bytes(b"not sqlite")
    corrupt_before = corrupt_paths.daemon_db.read_bytes()

    corrupt = inspect_hub(corrupt_paths)
    corrupt_archive = DoctorArchive(corrupt_paths, timestamp="stamp")
    assert repair_hub(corrupt_paths, corrupt_archive) == []
    assert corrupt.exit_code == 1
    assert corrupt_paths.daemon_db.read_bytes() == corrupt_before
    assert corrupt_archive.path is None

    forward_paths = _paths(tmp_path / "forward")
    with sqlite3.connect(forward_paths.daemon_db) as connection:
        connection.execute("PRAGMA user_version = 99")
    forward_before = forward_paths.daemon_db.read_bytes()

    forward = inspect_hub(forward_paths)
    forward_archive = DoctorArchive(forward_paths, timestamp="stamp")
    assert repair_hub(forward_paths, forward_archive) == []
    assert forward.exit_code == 1
    assert _checks(forward)["database.version"] is Severity.ERROR
    assert forward_paths.daemon_db.read_bytes() == forward_before
    assert forward_archive.path is None


def test_extra_schema_objects_are_retained_as_information(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    Store(db_path=paths.daemon_db, task_dir=paths.root / "tasks")
    with sqlite3.connect(paths.daemon_db) as connection:
        connection.execute("CREATE TABLE future_data (id TEXT PRIMARY KEY)")
        connection.execute("ALTER TABLE agents ADD COLUMN future_field TEXT")

    report = inspect_hub(paths)

    assert report.exit_code == 0
    assert _checks(report)["database.extras"] is Severity.INFO
    with sqlite3.connect(paths.daemon_db) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'future_data'").fetchone()
        assert "future_field" in {row[1] for row in connection.execute("PRAGMA table_info(agents)")}


def test_duplicate_handles_block_automatic_migration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with sqlite3.connect(paths.daemon_db) as connection:
        connection.execute("CREATE TABLE agents (id TEXT PRIMARY KEY, role TEXT, agent_handle TEXT)")
        connection.executemany(
            "INSERT INTO agents (id, role, agent_handle) VALUES (?, 'agent', 'duplicate')",
            [("one",), ("two",)],
        )
    before = paths.daemon_db.read_bytes()
    archive = DoctorArchive(paths, timestamp="stamp")

    report = inspect_hub(paths)
    errors = repair_hub(paths, archive)

    assert report.exit_code == 1
    assert _checks(report)["database.invariants"] is Severity.ERROR
    assert errors == []
    assert paths.daemon_db.read_bytes() == before
    assert archive.path is None


def test_missing_workstream_snapshot_is_backfilled_offline(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    Store(db_path=paths.daemon_db, task_dir=paths.root / "tasks")
    with sqlite3.connect(paths.daemon_db) as connection:
        connection.execute(
            """
            INSERT INTO workstreams (
                id, slug, label, brief, source_dossier_path, status, version, created_at, updated_at
            ) VALUES ('ws-1', 'alpha', 'Alpha', 'Brief', '/tmp/d.md', 'open', 1, 't0', 't1')
            """
        )
    archive = DoctorArchive(paths, timestamp="stamp")

    checked = inspect_hub(paths)
    errors = repair_hub(paths, archive)

    assert _checks(checked)["database.invariants"] is Severity.REPAIRABLE
    assert errors == []
    with sqlite3.connect(paths.daemon_db) as connection:
        row = connection.execute(
            "SELECT label, brief FROM workstream_versions WHERE workstream_id = 'ws-1' AND version = 1"
        ).fetchone()
    assert row == ("Alpha", "Brief")


def test_logical_orphans_are_reported_without_mutation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    Store(db_path=paths.daemon_db, task_dir=paths.root / "tasks")
    with sqlite3.connect(paths.daemon_db) as connection:
        connection.execute("INSERT INTO runs (id, agent_id, status) VALUES ('run-1', 'missing', 'failed')")
    before = paths.daemon_db.read_bytes()

    report = inspect_hub(paths)

    assert report.exit_code == 0
    assert _checks(report)["database.orphans"] is Severity.WARNING
    assert paths.daemon_db.read_bytes() == before


def test_database_directory_is_reported_without_opening(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    paths.daemon_db.mkdir(parents=True)

    report = inspect_hub(paths)

    assert report.exit_code == 1
    assert _checks(report)["database.type"] is Severity.ERROR


def test_database_symlink_is_never_followed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    target = tmp_path / "target.db"
    Store(db_path=target, task_dir=tmp_path / "tasks")
    paths.daemon_db.symlink_to(target)

    report = inspect_hub(paths)
    archive = DoctorArchive(paths, timestamp="stamp")

    assert report.exit_code == 1
    assert _checks(report)["database.symlink"] is Severity.ERROR
    assert repair_hub(paths, archive) == []
    assert paths.daemon_db.is_symlink()
    assert target.exists()
