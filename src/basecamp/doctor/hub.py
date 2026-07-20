"""Read-only hub Store checks and narrowly-gated offline migration."""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.store import Store
from basecamp.hub.store.contract import (
    MIGRATABLE_COLUMNS,
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    RETIRED_COLUMNS,
    STORE_USER_VERSION,
)

from .archive import DoctorArchive
from .models import DoctorCheck, DoctorPaths, DoctorReport, RepairAction, RepairKind, Severity
from .process import DaemonSpawnLock, DaemonState, DaemonStatus, inspect_daemon


@dataclass(frozen=True)
class HubState:
    report: DoctorReport
    daemon: DaemonStatus
    safe_to_repair: bool

    @property
    def needs_repair(self) -> bool:
        return any(action.kind is RepairKind.DATABASE for action in self.report.actions)


def inspect_hub(paths: DoctorPaths) -> DoctorReport:
    """Inspect daemon liveness and Store integrity without spawning or writing."""
    return _build_state(paths).report


def repair_hub(paths: DoctorPaths, archive: DoctorArchive) -> list[DoctorCheck]:
    """Back up and run the canonical Store migrations only while provably offline."""
    state = _build_state(paths)
    if not state.needs_repair or not state.safe_to_repair:
        return []
    if state.daemon.state is not DaemonState.DOWN:
        return [_repair_error("live", "Hub schema repair requires the daemon to be fully stopped.", paths.daemon_db)]

    try:
        with DaemonSpawnLock(paths.daemon_spawn_lock) as lock:
            rechecked = inspect_daemon(
                paths.daemon_socket,
                paths.daemon_pid,
                paths.daemon_spawn_lock,
                ignore_spawn_lock=True,
            )
            if rechecked.state is not DaemonState.DOWN:
                return [
                    _repair_error(
                        "race", "Hub liveness changed before schema repair; no changes made.", paths.daemon_db
                    )
                ]
            _backup_database(paths.daemon_db, archive, lock)
            lock.refresh(force=True)
            lock.run_while_refreshing(lambda: Store(db_path=paths.daemon_db, task_dir=paths.root / "tasks"))
    except FileExistsError:
        return [_repair_error("spawn_lock", "Hub spawn lock is held; no database changes were made.", paths.daemon_db)]
    except (OSError, sqlite3.Error) as exc:
        return [_repair_error("failed", f"Hub schema repair failed: {exc}", paths.daemon_db)]
    return []


def _build_state(paths: DoctorPaths) -> HubState:
    report = DoctorReport()
    daemon = inspect_daemon(paths.daemon_socket, paths.daemon_pid, paths.daemon_spawn_lock)
    _report_daemon(daemon, report, paths)

    try:
        mode = paths.daemon_db.lstat().st_mode
    except FileNotFoundError:
        report.add_check(
            DoctorCheck("database", "missing", Severity.INFO, "Hub database is not initialized.", paths.daemon_db)
        )
        return HubState(report, daemon, safe_to_repair=False)
    except OSError as exc:
        report.add_check(
            DoctorCheck(
                "database", "unreadable", Severity.ERROR, f"Could not inspect hub database: {exc}", paths.daemon_db
            )
        )
        return HubState(report, daemon, safe_to_repair=False)

    if stat.S_ISLNK(mode):
        report.add_check(
            DoctorCheck(
                "database", "symlink", Severity.ERROR, "Hub database is a symlink; repair is disabled.", paths.daemon_db
            )
        )
        return HubState(report, daemon, safe_to_repair=False)
    if not stat.S_ISREG(mode):
        report.add_check(
            DoctorCheck("database", "type", Severity.ERROR, "Hub database is not a regular file.", paths.daemon_db)
        )
        return HubState(report, daemon, safe_to_repair=False)

    try:
        with closing(_read_only_connection(paths.daemon_db)) as connection:
            safe_to_repair = _inspect_database(connection, report, paths.daemon_db)
    except sqlite3.Error as exc:
        report.add_check(
            DoctorCheck("database", "open", Severity.ERROR, f"Could not read hub database: {exc}", paths.daemon_db)
        )
        return HubState(report, daemon, safe_to_repair=False)
    return HubState(report, daemon, safe_to_repair=safe_to_repair)


def _report_daemon(status: DaemonStatus, report: DoctorReport, paths: DoctorPaths) -> None:
    if status.state is DaemonState.LIVE and status.protocol == PROTOCOL_VERSION:
        report.add_check(DoctorCheck("hub", "liveness", Severity.PASS, "Hub daemon is healthy.", paths.daemon_socket))
    elif status.state is DaemonState.LIVE:
        report.add_check(
            DoctorCheck(
                "hub",
                "protocol",
                Severity.WARNING,
                f"Hub daemon protocol differs from the current protocol ({PROTOCOL_VERSION}).",
                paths.daemon_socket,
            )
        )
    elif status.state is DaemonState.DOWN:
        report.add_check(
            DoctorCheck("hub", "liveness", Severity.INFO, "Hub daemon is not running.", paths.daemon_socket)
        )
    else:
        detail = f" ({status.detail})" if status.detail else ""
        report.add_check(
            DoctorCheck(
                "hub",
                "liveness",
                Severity.WARNING,
                f"Hub daemon liveness is ambiguous; database repair is disabled{detail}.",
                paths.daemon_socket,
            )
        )


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve(strict=True).as_uri()}?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _inspect_database(connection: sqlite3.Connection, report: DoctorReport, path: Path) -> bool:
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
    if integrity != ["ok"]:
        report.add_check(
            DoctorCheck("database", "integrity", Severity.ERROR, "Hub database integrity check failed.", path)
        )
        return False
    report.add_check(DoctorCheck("database", "integrity", Severity.PASS, "Hub database integrity is valid.", path))

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > STORE_USER_VERSION:
        report.add_check(
            DoctorCheck(
                "database",
                "version",
                Severity.ERROR,
                f"Hub database version {version} is newer than supported version {STORE_USER_VERSION}.",
                path,
            )
        )
        return False
    if version < STORE_USER_VERSION:
        report.add_check(
            DoctorCheck(
                "database",
                "version",
                Severity.REPAIRABLE,
                f"Hub database version can be migrated to version {STORE_USER_VERSION}.",
                path,
            )
        )
    else:
        report.add_check(DoctorCheck("database", "version", Severity.PASS, "Hub database version is current.", path))

    repair_reasons, schema_errors = _schema_issues(connection)
    invariant_gaps, invariant_errors = _migration_invariants(connection, version)
    repair_reasons.extend(invariant_gaps)
    if version < STORE_USER_VERSION:
        repair_reasons.append("store version")

    if invariant_errors:
        report.add_check(
            DoctorCheck(
                "database",
                "invariants",
                Severity.ERROR,
                "Hub database contains state that canonical migrations cannot repair automatically.",
                path,
            )
        )
    elif invariant_gaps:
        report.add_check(
            DoctorCheck(
                "database",
                "invariants",
                Severity.REPAIRABLE,
                "Hub database migration invariants can be backfilled.",
                path,
            )
        )
    else:
        report.add_check(
            DoctorCheck("database", "invariants", Severity.PASS, "Hub database migration invariants are current.", path)
        )

    if schema_errors:
        report.add_check(
            DoctorCheck(
                "database",
                "schema",
                Severity.ERROR,
                "Hub database has schema drift that canonical migrations cannot repair automatically.",
                path,
            )
        )
    elif repair_reasons:
        severity = Severity.ERROR if invariant_errors else Severity.REPAIRABLE
        message = (
            "Hub database migrations are blocked by unresolved data invariants."
            if invariant_errors
            else "Hub database has Store-owned schema migrations pending."
        )
        report.add_check(DoctorCheck("database", "schema", severity, message, path))
        if not invariant_errors:
            report.add_action(
                RepairAction(
                    code="database.migrate",
                    kind=RepairKind.DATABASE,
                    description="Back up the hub database and run canonical Store migrations.",
                    paths=(path,),
                )
            )
    else:
        report.add_check(DoctorCheck("database", "schema", Severity.PASS, "Hub database schema is current.", path))

    _report_extras(connection, report, path)
    _report_orphans(connection, report, path)
    return not schema_errors and not invariant_errors


def _schema_issues(connection: sqlite3.Connection) -> tuple[list[str], list[str]]:
    tables = _tables(connection)
    repairable: list[str] = []
    errors: list[str] = []
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            repairable.append(f"table:{table}")
            continue
        missing = required - _columns(connection, table)
        migratable = MIGRATABLE_COLUMNS.get(table, frozenset())
        repairable.extend(f"column:{table}.{column}" for column in sorted(missing & migratable))
        errors.extend(f"column:{table}.{column}" for column in sorted(missing - migratable))
    for table, required in REQUIRED_INDEXES.items():
        if table in tables:
            indexes = _indexes(connection, table)
            repairable.extend(f"index:{table}.{index}" for index in sorted(required - indexes))
    if sqlite3.sqlite_version_info >= (3, 35, 0):
        for table, retired in RETIRED_COLUMNS.items():
            if table in tables:
                repairable.extend(
                    f"retired:{table}.{column}" for column in sorted(retired & _columns(connection, table))
                )
    return repairable, errors


def _migration_invariants(connection: sqlite3.Connection, version: int) -> tuple[list[str], list[str]]:
    tables = _tables(connection)
    gaps: list[str] = []
    errors: list[str] = []
    if "agents" in tables and "agent_handle" in _columns(connection, "agents"):
        if _count(connection, "SELECT COUNT(*) FROM agents WHERE agent_handle IS NULL OR agent_handle = ''"):
            gaps.append("agent handles")
        duplicates = _count(
            connection,
            "SELECT COUNT(*) FROM (SELECT agent_handle FROM agents WHERE agent_handle IS NOT NULL "
            "GROUP BY agent_handle HAVING COUNT(*) > 1)",
        )
        if duplicates:
            errors.append("duplicate agent handles")
        if (
            "role" in _columns(connection, "agents")
            and version >= STORE_USER_VERSION
            and _count(connection, "SELECT COUNT(*) FROM agents WHERE role = 'session'")
        ):
            errors.append("legacy roles after version migration")
    required = {"workstreams", "workstream_versions"}
    if (
        required <= tables
        and {"id", "version"} <= _columns(connection, "workstreams")
        and {"workstream_id", "version"} <= _columns(connection, "workstream_versions")
    ):
        missing_versions = _count(
            connection,
            "SELECT COUNT(*) FROM workstreams w WHERE NOT EXISTS "
            "(SELECT 1 FROM workstream_versions v "
            "WHERE v.workstream_id = w.id AND v.version = w.version)",
        )
        if missing_versions:
            gaps.append("workstream version snapshots")
    return gaps, errors


def _report_extras(connection: sqlite3.Connection, report: DoctorReport, path: Path) -> None:
    tables = _tables(connection)
    extra_tables = {name for name in tables - REQUIRED_COLUMNS.keys() if not name.startswith("sqlite_")}
    extra_columns = sum(
        len(_columns(connection, table) - required - RETIRED_COLUMNS.get(table, frozenset()))
        for table, required in REQUIRED_COLUMNS.items()
        if table in tables
    )
    extra_indexes = sum(
        len(
            {
                index
                for index in _indexes(connection, table) - REQUIRED_INDEXES.get(table, frozenset())
                if not index.startswith("sqlite_autoindex_")
            }
        )
        for table in REQUIRED_COLUMNS
        if table in tables
    )
    if extra_tables or extra_columns or extra_indexes:
        report.add_check(
            DoctorCheck(
                "database",
                "extras",
                Severity.INFO,
                "Hub database contains extra schema objects; they are retained.",
                path,
            )
        )


def _report_orphans(connection: sqlite3.Connection, report: DoctorReport, path: Path) -> None:
    tables = _tables(connection)
    queries = (
        (
            {"agents": {"id"}, "runs": {"agent_id"}},
            "SELECT COUNT(*) FROM runs r LEFT JOIN agents a ON a.id = r.agent_id "
            "WHERE r.agent_id IS NOT NULL AND a.id IS NULL",
        ),
        (
            {"runs": {"id"}, "run_events": {"run_id"}},
            "SELECT COUNT(*) FROM run_events e LEFT JOIN runs r ON r.id = e.run_id WHERE r.id IS NULL",
        ),
        (
            {"workstreams": {"id"}, "workstream_agents": {"workstream_id"}},
            "SELECT COUNT(*) FROM workstream_agents a LEFT JOIN workstreams w ON w.id = a.workstream_id "
            "WHERE w.id IS NULL",
        ),
        (
            {"workstreams": {"id"}, "workstream_versions": {"workstream_id"}},
            "SELECT COUNT(*) FROM workstream_versions v LEFT JOIN workstreams w ON w.id = v.workstream_id "
            "WHERE w.id IS NULL",
        ),
    )
    has_orphans = any(
        all(table in tables and columns <= _columns(connection, table) for table, columns in required.items())
        and _count(connection, query)
        for required, query in queries
    )
    if has_orphans:
        report.add_check(
            DoctorCheck(
                "database",
                "orphans",
                Severity.WARNING,
                "Hub database contains logical orphan rows; they were not changed.",
                path,
            )
        )


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _indexes(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA index_list("{table}")').fetchall()}


def _count(connection: sqlite3.Connection, query: str) -> int:
    row: Any = connection.execute(query).fetchone()
    return int(row[0]) if row is not None else 0


def _backup_database(source: Path, archive: DoctorArchive, lock: DaemonSpawnLock) -> Path:
    destination = archive.reserve_backup_path(Path("swarm") / "daemon.db")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with (
            closing(_read_only_connection(source)) as source_connection,
            closing(sqlite3.connect(destination)) as target_connection,
        ):

            def progress(_status: int, _remaining: int, _total: int) -> None:
                lock.refresh()

            source_connection.backup(target_connection, pages=256, progress=progress, sleep=0.05)
            _require_valid_backup(target_connection)
    except (OSError, sqlite3.Error, ValueError):
        destination.unlink(missing_ok=True)
        raise
    destination.chmod(0o600)
    archive.record_backup(source, destination)
    return destination


def _require_valid_backup(connection: sqlite3.Connection) -> None:
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check").fetchall()]
    if integrity != ["ok"]:
        msg = "Hub database backup failed its integrity check."
        raise sqlite3.DatabaseError(msg)


def _repair_error(code: str, message: str, path: Path) -> DoctorCheck:
    return DoctorCheck("database", f"repair_{code}", Severity.ERROR, message, path)
