"""SQLite-backed persistence for daemon agents and runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_db_path() -> Path:
    """Return the default Basecamp swarm daemon database path."""

    return Path.home() / ".pi" / "basecamp" / "swarm" / "daemon.db"


TERMINAL_STATUSES = ("completed", "failed")
RUN_SUMMARY_DEFAULT_LIMIT = 5
RUN_SUMMARY_MAX_LIMIT = 100
RUN_SUMMARY_PREVIEW_CHARS = 160


class ActiveRunExistsError(Exception):
    """Raised when an agent already has an active primary run."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"agent {agent_id} already has an active primary run")


class DuplicateAgentHandleError(Exception):
    """Raised when an agent handle is already assigned to another agent."""

    def __init__(self, agent_handle: str) -> None:
        super().__init__(f"agent handle {agent_handle!r} is already in use")


def _fallback_agent_handle(agent_id: str) -> str:
    return agent_id


def _preview_text(value: str | None, *, limit: int = RUN_SUMMARY_PREVIEW_CHARS) -> str | None:
    if value is None:
        return None

    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


class Store:
    """Daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    sibling_group TEXT,
                    depth INTEGER,
                    role TEXT,
                    session_name TEXT,
                    cwd TEXT,
                    created_at TEXT,
                    last_seen_at TEXT,
                    current_run_id TEXT,
                    agent_handle TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    status TEXT CHECK(status IN ('pending','running','completed','failed')),
                    dispatcher_id TEXT,
                    spec_json TEXT,
                    report_token_hash TEXT,
                    result TEXT,
                    error TEXT,
                    exit_code INTEGER,
                    created_at TEXT,
                    started_at TEXT,
                    ended_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT,
                    seq INTEGER,
                    kind TEXT,
                    payload_json TEXT,
                    ts TEXT,
                    PRIMARY KEY (run_id, seq)
                )
                """
            )
            self._ensure_agents_current_run_id_column(connection)
            self._ensure_agents_agent_handle_column(connection)
            self._ensure_runs_dispatcher_id_column(connection)
            self._ensure_runs_exit_code_column(connection)
            self._ensure_runs_report_token_hash_column(connection)

    def _ensure_agents_current_run_id_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "current_run_id" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN current_run_id TEXT")

    def _ensure_agents_agent_handle_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "agent_handle" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN agent_handle TEXT")

        rows = connection.execute("SELECT id FROM agents WHERE agent_handle IS NULL OR agent_handle = ''").fetchall()
        for row in rows:
            agent_id = row[0]
            connection.execute(
                "UPDATE agents SET agent_handle = ? WHERE id = ?",
                (_fallback_agent_handle(agent_id), agent_id),
            )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_agent_handle_unique
            ON agents(agent_handle)
            WHERE agent_handle IS NOT NULL
            """
        )

    def _ensure_runs_dispatcher_id_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "dispatcher_id" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN dispatcher_id TEXT")

    def _ensure_runs_exit_code_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "exit_code" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN exit_code INTEGER")

    def _ensure_runs_report_token_hash_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(runs)").fetchall()
        names = {column[1] for column in columns}
        if "report_token_hash" not in names:
            connection.execute("ALTER TABLE runs ADD COLUMN report_token_hash TEXT")

    def upsert_agent(
        self,
        *,
        agent_id: str,
        parent_id: str | None,
        sibling_group: str | None,
        depth: int,
        role: str,
        session_name: str,
        cwd: str,
        agent_handle: str | None = None,
    ) -> None:
        """Insert/update an agent row and refresh last-seen timestamp."""

        now = self._now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT agent_handle FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
            stored_handle = existing[0] if existing is not None else None
            next_handle = agent_handle or stored_handle or _fallback_agent_handle(agent_id)

            duplicate = connection.execute(
                "SELECT id FROM agents WHERE agent_handle = ? AND id != ? LIMIT 1",
                (next_handle, agent_id),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateAgentHandleError(next_handle)

            connection.execute(
                """
                INSERT INTO agents (
                    id,
                    parent_id,
                    sibling_group,
                    depth,
                    role,
                    session_name,
                    cwd,
                    created_at,
                    last_seen_at,
                    agent_handle
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    parent_id = excluded.parent_id,
                    sibling_group = excluded.sibling_group,
                    depth = excluded.depth,
                    role = excluded.role,
                    session_name = excluded.session_name,
                    cwd = excluded.cwd,
                    last_seen_at = excluded.last_seen_at,
                    agent_handle = excluded.agent_handle
                """,
                (
                    agent_id,
                    parent_id,
                    sibling_group,
                    depth,
                    role,
                    session_name,
                    cwd,
                    now,
                    now,
                    next_handle,
                ),
            )

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Fetch an agent by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row is not None else None

    def get_agent_by_handle(self, agent_handle: str) -> dict[str, Any] | None:
        """Fetch an agent by public handle as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM agents WHERE agent_handle = ?", (agent_handle,)).fetchone()
            return dict(row) if row is not None else None

    def create_run(
        self,
        *,
        run_id: str,
        agent_id: str,
        dispatcher_id: str,
        spec: dict[str, Any],
        report_token_hash: str | None = None,
    ) -> None:
        """Create a running run row."""

        now = self._now()
        with self._connect() as connection:
            existing_active = connection.execute(
                """
                SELECT id
                FROM runs
                WHERE agent_id = ?
                  AND status NOT IN (?, ?)
                LIMIT 1
                """,
                (agent_id, *TERMINAL_STATUSES),
            ).fetchone()
            if existing_active is not None:
                raise ActiveRunExistsError(agent_id)

            connection.execute(
                """
                INSERT INTO runs (
                    id,
                    agent_id,
                    status,
                    dispatcher_id,
                    spec_json,
                    report_token_hash,
                    created_at,
                    started_at
                )
                VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (run_id, agent_id, dispatcher_id, json.dumps(spec), report_token_hash, now, now),
            )
            connection.execute(
                "UPDATE agents SET current_run_id = ? WHERE id = ?",
                (run_id, agent_id),
            )

    def set_run_exit_code(self, *, run_id: str, exit_code: int | None) -> None:
        """Persist subprocess exit code for a run."""

        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET exit_code = ? WHERE id = ?",
                (exit_code, run_id),
            )

    def set_run_result(
        self,
        *,
        run_id: str,
        status: str,
        result: str | None,
        error: str | None,
    ) -> None:
        """Persist terminal result/error state for a run."""

        ended_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, result = ?, error = ?, ended_at = ?
                WHERE id = ?
                """,
                (status, result, error, ended_at, run_id),
            )
            if cursor.rowcount == 0:
                return

    def set_run_result_if_unset(
        self,
        *,
        run_id: str,
        status: str,
        result: str | None,
        error: str | None,
    ) -> bool:
        """Set terminal run result using first-writer-wins semantics."""

        ended_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = ?, result = ?, error = ?, ended_at = ?
                WHERE id = ?
                  AND status IN ('pending', 'running')
                """,
                (status, result, error, ended_at, run_id),
            )
            if cursor.rowcount == 0:
                return False

            return True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a run by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            spec_json = result.get("spec_json")
            if isinstance(spec_json, str):
                result["spec_json"] = json.loads(spec_json)
            return result

    def _resolve_requester_root(self, requester_node_id: str) -> str | None:
        """Resolve the root id for a node by following parent links defensively."""

        visited: set[str] = set()
        current = requester_node_id

        while isinstance(current, str) and current not in visited:
            visited.add(current)
            row = self.get_agent(current)
            if row is None:
                return None

            parent_id = row.get("parent_id")
            if not isinstance(parent_id, str) or not parent_id.strip():
                return current
            if self.get_agent(parent_id) is None:
                return current
            current = parent_id

        return current if isinstance(current, str) else None

    def get_root_agent_directory(
        self,
        *,
        requester_node_id: str,
        awaitable: bool = False,
    ) -> list[dict[str, Any]]:
        """List non-session agents under the caller's root with safe status metadata."""

        root_id = self._resolve_requester_root(requester_node_id)
        if root_id is None:
            return []

        awaitable_filter = "" if not awaitable else " AND r.id IS NOT NULL AND r.dispatcher_id = ? "
        query = f"""
            WITH RECURSIVE scoped_agents(id, parent_id, path) AS (
                SELECT id, parent_id, ',' || id || ','
                FROM agents
                WHERE id = ?
                UNION
                SELECT child.id,
                       child.parent_id,
                       path || child.id || ','
                FROM agents AS child
                INNER JOIN scoped_agents AS s ON child.parent_id = s.id
                WHERE instr(s.path, ',' || child.id || ',') = 0
            )
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                a.parent_id,
                a.role,
                a.session_name,
                a.depth,
                CASE
                    WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                    ELSE 'idle'
                END AS status,
                CASE
                    WHEN r.id IS NOT NULL AND r.dispatcher_id = ? THEN 1
                    ELSE 0
                END AS awaitable
            FROM scoped_agents AS s
            INNER JOIN agents AS a ON a.id = s.id
            LEFT JOIN runs AS r ON r.id = a.current_run_id
            WHERE a.role != 'session'
            {awaitable_filter}
            ORDER BY a.depth ASC, a.id ASC
            """

        params: tuple[Any, ...] = (root_id, requester_node_id)
        if awaitable:
            params = (root_id, requester_node_id, requester_node_id)

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()

        return [
            {
                "agent_id": row["agent_id"],
                "agent_handle": row["agent_handle"],
                "parent_id": row["parent_id"],
                "role": row["role"],
                "session_name": row["session_name"],
                "depth": row["depth"],
                "status": row["status"],
                "awaitable": bool(row["awaitable"]),
            }
            for row in rows
        ]

    def get_agents_current_runs(
        self,
        agent_ids: list[str],
        *,
        dispatcher_id: str,
    ) -> list[dict[str, Any]]:
        """Return current primary-run projections for requested agents.

        Only runs owned by ``dispatcher_id`` are exposed. Missing agents,
        missing current runs, and unauthorized agents are returned without any
        run state in the row.
        """

        if not agent_ids:
            return []

        placeholders = ", ".join("?" for _ in agent_ids)
        query = f"""
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                r.id AS run_id,
                r.status AS status,
                r.result AS result,
                r.error AS error
            FROM agents AS a
            LEFT JOIN runs AS r
                ON r.id = a.current_run_id
               AND r.dispatcher_id = ?
            WHERE a.id IN ({placeholders})
            """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, (dispatcher_id, *agent_ids)).fetchall()

        return [dict(row) for row in rows]

    def get_agents_current_runs_by_handles(
        self,
        agent_handles: list[str],
        *,
        dispatcher_id: str,
    ) -> list[dict[str, Any]]:
        """Return current primary-run projections for requested agent handles."""

        if not agent_handles:
            return []

        placeholders = ", ".join("?" for _ in agent_handles)
        query = f"""
            SELECT
                a.id AS agent_id,
                a.agent_handle,
                r.id AS run_id,
                r.status AS status,
                r.result AS result,
                r.error AS error
            FROM agents AS a
            LEFT JOIN runs AS r
                ON r.id = a.current_run_id
               AND r.dispatcher_id = ?
            WHERE a.agent_handle IN ({placeholders})
            """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, (dispatcher_id, *agent_handles)).fetchall()

        return [dict(row) for row in rows]

    def get_run_wait_results(self, run_ids: list[str], *, terminal_only: bool = False) -> list[dict[str, Any]]:
        """Return wait result projections for requested run ids.

        When ``terminal_only`` is true, returns only completed/failed runs.
        """

        if not run_ids:
            return []

        placeholders = ", ".join("?" for _ in run_ids)
        where_terminal = " AND status IN ('completed', 'failed')" if terminal_only else ""
        query = f"SELECT id, status, result, error FROM runs WHERE id IN ({placeholders}){where_terminal}"

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, tuple(run_ids)).fetchall()

        return [
            {
                "run_id": row["id"],
                "status": row["status"],
                "result": row["result"],
                "error": row["error"],
            }
            for row in rows
        ]

    def get_run_summary(self, root_id: str, *, limit: int = RUN_SUMMARY_DEFAULT_LIMIT) -> dict[str, Any]:
        """Return a safe run summary for a root agent subtree."""

        safe_limit = max(0, min(limit, RUN_SUMMARY_MAX_LIMIT))

        recursive_scope = """
            WITH RECURSIVE scoped_agents(id) AS (
                SELECT id FROM agents WHERE id = ?
                UNION
                SELECT child.id
                FROM agents AS child
                INNER JOIN scoped_agents AS parent ON child.parent_id = parent.id
            )
        """

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row

            counts_row = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    COALESCE(SUM(CASE WHEN r.status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_count,
                    COALESCE(SUM(CASE WHEN r.status = 'running' THEN 1 ELSE 0 END), 0) AS running_count,
                    COALESCE(SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_count,
                    COALESCE(SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
                    COUNT(r.id) AS total_count
                FROM runs AS r
                WHERE r.agent_id IN (SELECT id FROM scoped_agents)
                """,
                (root_id,),
            ).fetchone()

            run_rows = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    r.id AS run_id,
                    r.agent_id,
                    a.agent_handle,
                    a.parent_id,
                    a.role,
                    a.session_name,
                    r.status,
                    r.result,
                    r.error,
                    r.exit_code,
                    r.created_at,
                    r.started_at,
                    r.ended_at
                FROM runs AS r
                INNER JOIN agents AS a ON a.id = r.agent_id
                WHERE r.agent_id IN (SELECT id FROM scoped_agents)
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT ?
                """,
                (root_id, safe_limit),
            ).fetchall()

        runs = [
            {
                "run_id": row["run_id"],
                "agent_id": row["agent_id"],
                "agent_handle": row["agent_handle"],
                "parent_id": row["parent_id"],
                "role": row["role"],
                "session_name": row["session_name"],
                "status": row["status"],
                "result_preview": _preview_text(row["result"]),
                "error_preview": _preview_text(row["error"]),
                "exit_code": row["exit_code"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
            }
            for row in run_rows
        ]

        return {
            "root_id": root_id,
            "counts": {
                "pending": counts_row["pending_count"],
                "running": counts_row["running_count"],
                "completed": counts_row["completed_count"],
                "failed": counts_row["failed_count"],
                "total": counts_row["total_count"],
            },
            "runs": runs,
        }

    def are_runs_terminal(self, run_ids: list[str]) -> bool:
        """Return True when all requested run ids exist and are terminal."""

        if not run_ids:
            return True

        placeholders = ", ".join("?" for _ in run_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, status FROM runs WHERE id IN ({placeholders})",
                tuple(run_ids),
            ).fetchall()

        by_id = {row[0]: row[1] for row in rows}
        if len(by_id) != len(run_ids):
            return False
        return all(by_id[run_id] in TERMINAL_STATUSES for run_id in run_ids)

    def append_run_event(self, *, run_id: str, kind: str, payload: dict[str, Any]) -> int:
        """Append an ordered event row for a run and return its sequence number."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            next_seq = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO run_events (run_id, seq, kind, payload_json, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, int(next_seq), kind, json.dumps(payload), self._now()),
            )
            return int(next_seq)

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        """Return run events in sequence order."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT run_id, seq, kind, payload_json, ts FROM run_events WHERE run_id = ? ORDER BY seq ASC",
                (run_id,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            payload_json = data.get("payload_json")
            if isinstance(payload_json, str):
                data["payload_json"] = json.loads(payload_json)
            results.append(data)
        return results
