"""SQLite-backed persistence for daemon agents and runs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


def default_db_path() -> Path:
    """Return the default Basecamp swarm daemon database path."""

    return Path.home() / ".pi" / "basecamp" / "swarm" / "daemon.db"


def default_tasks_dir() -> Path:
    """Return the default Basecamp task-log directory."""

    return Path.home() / ".pi" / "basecamp" / "tasks"


TERMINAL_STATUSES = ("completed", "failed")
MESSAGE_STATUS_ACCEPTED = "accepted"
MESSAGE_STATUS_SENT = "sent"
MESSAGE_STATUS_QUEUED = "queued"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_UNAVAILABLE = "unavailable"
MESSAGE_STATUS_UNKNOWN = "unknown"
MESSAGE_STATUSES = (
    MESSAGE_STATUS_ACCEPTED,
    MESSAGE_STATUS_SENT,
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_UNAVAILABLE,
)
MESSAGE_TERMINAL_DELIVERY_STATUSES = (
    MESSAGE_STATUS_QUEUED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_UNAVAILABLE,
    MESSAGE_STATUS_UNKNOWN,
)
AgentRelation = Literal["self", "parent", "ancestor", "child", "descendant", "peer", "unknown"]
RUN_SUMMARY_DEFAULT_LIMIT = 5
RUN_SUMMARY_MAX_LIMIT = 100
RUN_SUMMARY_PREVIEW_CHARS = 160
RUN_SUMMARY_DISPLAY_CHARS = 240
RUN_SUMMARY_TASK_PLAN_LIMIT = 20
RUN_MESSAGES_DEFAULT_LIMIT = 3
RUN_MESSAGES_MAX_LIMIT = 3
RUN_SUMMARY_ACTIVITY_LIMIT = 10
RUN_SUMMARY_SKILLS_LIMIT = 20
RUN_SUMMARY_TASK_LOG_MAX_BYTES = 256 * 1024
_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ACTIVITY_KINDS = {
    "tool_call",
    "tool_result",
    "assistant_output",
    "thinking",
    "agent_result",
    "tool_execution_start",
    "tool_execution_end",
    "turn_end",
}
_ACTIVITY_PAYLOAD_KEYS = ("category", "label", "snippet", "toolName", "isError", "turnIndex", "toolCount")


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


def _safe_product_role(value: str | None) -> str | None:
    return _display_text(value, limit=64)


def _display_text(value: Any, *, limit: int = RUN_SUMMARY_DISPLAY_CHARS) -> str | None:
    if not isinstance(value, str):
        return None

    text = _ANSI_PATTERN.sub("", value)
    text = _CONTROL_PATTERN.sub("", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"


def _preview_text(value: str | None, *, limit: int = RUN_SUMMARY_PREVIEW_CHARS) -> str | None:
    return _display_text(value, limit=limit)


def _message_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    text = _ANSI_PATTERN.sub("", value)
    text = _CONTROL_PATTERN.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _is_valid_agent_id(agent_id: str) -> bool:
    return bool(_AGENT_ID_PATTERN.fullmatch(agent_id))


def _agent_id_short(agent_id: Any) -> str | None:
    if not isinstance(agent_id, str):
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", agent_id)
    if not normalized:
        return None
    return normalized[-8:]


def is_message_delivery_terminal(status: str) -> bool:
    """Return whether a public message status is terminal for wait semantics."""

    return status in MESSAGE_TERMINAL_DELIVERY_STATUSES


class Store:
    """Daemon persistence layer backed by SQLite."""

    def __init__(self, db_path: str | Path | None = None, task_dir: str | Path | None = None) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else default_db_path()
        self.task_dir = Path(task_dir).expanduser() if task_dir is not None else default_tasks_dir()
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
                    agent_handle TEXT,
                    agent_type TEXT,
                    run_kind TEXT,
                    model TEXT,
                    session_file TEXT,
                    product_role TEXT
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    root_id TEXT,
                    sender_node_id TEXT,
                    sender_handle TEXT,
                    target_agent_id TEXT,
                    target_handle TEXT,
                    content TEXT,
                    interrupt INTEGER,
                    status TEXT CHECK(status IN ('accepted','sent','queued','failed','unavailable')),
                    error TEXT,
                    created_at TEXT,
                    sent_at TEXT,
                    queued_at TEXT,
                    failed_at TEXT
                )
                """
            )
            self._ensure_agents_current_run_id_column(connection)
            self._ensure_agents_agent_handle_column(connection)
            self._ensure_agents_metadata_columns(connection)
            self._ensure_agents_model_column(connection)
            self._ensure_agents_session_file_column(connection)
            self._ensure_agents_product_role_column(connection)
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

    def _ensure_agents_metadata_columns(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "agent_type" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN agent_type TEXT")
        if "run_kind" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN run_kind TEXT")

    def _ensure_agents_model_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "model" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN model TEXT")

    def _ensure_agents_session_file_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "session_file" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN session_file TEXT")

    def _ensure_agents_product_role_column(self, connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(agents)").fetchall()
        names = {column[1] for column in columns}
        if "product_role" not in names:
            connection.execute("ALTER TABLE agents ADD COLUMN product_role TEXT")

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
        agent_type: str | None = None,
        run_kind: str | None = None,
        model: str | None = None,
        session_file: str | None = None,
        product_role: str | None = None,
    ) -> None:
        """Insert/update an agent row and refresh last-seen timestamp."""

        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT agent_handle, agent_type, run_kind, model, sibling_group, session_file, product_role
                FROM agents
                WHERE id = ?
                """,
                (agent_id,),
            ).fetchone()
            stored_handle = existing[0] if existing is not None else None
            stored_agent_type = existing[1] if existing is not None else None
            stored_run_kind = existing[2] if existing is not None else None
            stored_model = existing[3] if existing is not None else None
            stored_sibling_group = existing[4] if existing is not None else None
            stored_session_file = existing[5] if existing is not None else None
            stored_product_role = existing[6] if existing is not None else None
            next_handle = agent_handle or stored_handle or _fallback_agent_handle(agent_id)
            next_agent_type = agent_type or stored_agent_type
            next_run_kind = run_kind or stored_run_kind
            next_model = model or stored_model
            next_sibling_group = sibling_group or stored_sibling_group
            next_session_file = session_file or stored_session_file
            next_product_role = _safe_product_role(product_role) or stored_product_role

            try:
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
                        agent_handle,
                        agent_type,
                        run_kind,
                        model,
                        session_file,
                        product_role
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id)
                    DO UPDATE SET
                        parent_id = excluded.parent_id,
                        sibling_group = excluded.sibling_group,
                        depth = excluded.depth,
                        role = excluded.role,
                        session_name = excluded.session_name,
                        cwd = excluded.cwd,
                        last_seen_at = excluded.last_seen_at,
                        agent_handle = excluded.agent_handle,
                        agent_type = excluded.agent_type,
                        run_kind = excluded.run_kind,
                        model = excluded.model,
                        session_file = excluded.session_file,
                        product_role = excluded.product_role
                    """,
                    (
                        agent_id,
                        parent_id,
                        next_sibling_group,
                        depth,
                        role,
                        session_name,
                        cwd,
                        now,
                        now,
                        next_handle,
                        next_agent_type,
                        next_run_kind,
                        next_model,
                        next_session_file,
                        next_product_role,
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "agents.agent_handle" in str(error):
                    raise DuplicateAgentHandleError(next_handle) from error
                raise

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

    def create_message(
        self,
        *,
        message_id: str,
        root_id: str,
        sender_node_id: str,
        sender_handle: str | None,
        target_agent_id: str,
        target_handle: str,
        content: str,
        interrupt: bool,
    ) -> None:
        """Persist a newly accepted peer message."""

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id,
                    root_id,
                    sender_node_id,
                    sender_handle,
                    target_agent_id,
                    target_handle,
                    content,
                    interrupt,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    root_id,
                    sender_node_id,
                    sender_handle,
                    target_agent_id,
                    target_handle,
                    content,
                    1 if interrupt else 0,
                    MESSAGE_STATUS_ACCEPTED,
                    self._now(),
                ),
            )

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Fetch a peer message by id as a dict, or None when absent."""

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
            return dict(row) if row is not None else None

    def mark_message_sent(self, message_id: str) -> bool:
        """Mark a non-terminal peer message as sent."""

        sent_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, sent_at = ?
                WHERE id = ?
                  AND status NOT IN (?, ?, ?)
                """,
                (
                    MESSAGE_STATUS_SENT,
                    sent_at,
                    message_id,
                    MESSAGE_STATUS_QUEUED,
                    MESSAGE_STATUS_FAILED,
                    MESSAGE_STATUS_UNAVAILABLE,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_queued(self, message_id: str) -> bool:
        """Mark a non-terminal peer message as queued for recipient handling."""

        queued_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, queued_at = ?, error = NULL
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_QUEUED,
                    queued_at,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_failed(self, message_id: str, error: str | None = None) -> bool:
        """Mark a non-terminal peer message as failed."""

        failed_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, failed_at = ?, error = ?
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_FAILED,
                    failed_at,
                    error,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def mark_message_unavailable(self, message_id: str, error: str | None = None) -> bool:
        """Mark a non-terminal peer message as unavailable for this phase."""

        failed_at = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE messages
                SET status = ?, failed_at = ?, error = ?
                WHERE id = ?
                  AND status IN (?, ?)
                """,
                (
                    MESSAGE_STATUS_UNAVAILABLE,
                    failed_at,
                    error,
                    message_id,
                    MESSAGE_STATUS_ACCEPTED,
                    MESSAGE_STATUS_SENT,
                ),
            )
            return cursor.rowcount > 0

    def get_message_status(self, requester_node_id: str, message_id: str) -> dict[str, Any]:
        """Return the public delivery status for a participant-visible peer message."""

        unknown = {
            "message_id": message_id,
            "status": MESSAGE_STATUS_UNKNOWN,
            "error": None,
            "created_at": None,
            "sent_at": None,
            "queued_at": None,
            "failed_at": None,
        }

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT
                    sender_node_id,
                    target_agent_id,
                    status,
                    error,
                    created_at,
                    sent_at,
                    queued_at,
                    failed_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

        if row is None:
            return unknown

        if requester_node_id not in {row["sender_node_id"], row["target_agent_id"]}:
            return unknown

        status = row["status"]
        if status not in MESSAGE_STATUSES:
            return unknown

        return {
            "message_id": message_id,
            "status": status,
            "error": row["error"],
            "created_at": row["created_at"],
            "sent_at": row["sent_at"],
            "queued_at": row["queued_at"],
            "failed_at": row["failed_at"],
        }

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

    def resolve_agent_root(self, agent_id: str) -> str | None:
        """Resolve the root id for an agent by following parent links defensively."""

        visited: set[str] = set()
        current = agent_id

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

    def can_ask(
        self,
        requester_node_id: str,
        target_agent_id: str,
        *,
        addressed_by_public_handle: bool = False,
    ) -> bool:
        """Return whether requester may fork-ask the target agent.

        Relationship reachability (self/ancestor/descendant/sibling) always
        authorizes. When the caller addressed the target by its known public
        handle, contact is also allowed without a live relationship: the handle
        is a routable contact address, not authorization for introspection.
        """

        if self._can_reach_agent(requester_node_id, target_agent_id):
            return True
        if addressed_by_public_handle:
            return self._can_contact_by_public_handle(requester_node_id, target_agent_id)
        return False

    def can_message(
        self,
        requester_node_id: str,
        target_agent_id: str,
        *,
        addressed_by_public_handle: bool = False,
    ) -> bool:
        """Return whether requester may send a live peer message to the target.

        See :meth:`can_ask` for how known-public-handle contact relates to
        relationship reachability.
        """

        if self._can_reach_agent(requester_node_id, target_agent_id):
            return True
        if addressed_by_public_handle:
            return self._can_contact_by_public_handle(requester_node_id, target_agent_id)
        return False

    def agent_relation(self, viewer_agent_id: str, other_agent_id: str) -> AgentRelation:
        """Return how the other agent relates to the viewer."""

        viewer = self.get_agent(viewer_agent_id)
        other = self.get_agent(other_agent_id)
        if viewer is None or other is None:
            return "unknown"
        if viewer_agent_id == other_agent_id:
            return "self"
        if viewer.get("parent_id") == other_agent_id:
            return "parent"
        if other.get("parent_id") == viewer_agent_id:
            return "child"
        if self._parent_chain_contains(viewer_agent_id, other_agent_id):
            return "ancestor"
        if self._parent_chain_contains(other_agent_id, viewer_agent_id):
            return "descendant"

        viewer_sibling_group = viewer.get("sibling_group")
        if viewer_sibling_group is not None and viewer_sibling_group == other.get("sibling_group"):
            return "peer"
        return "unknown"

    def _can_reach_agent(self, requester_node_id: str, target_agent_id: str) -> bool:
        requester = self.get_agent(requester_node_id)
        target = self.get_agent(target_agent_id)
        if requester is None or target is None:
            return False
        if requester_node_id == target_agent_id:
            return True

        if self._parent_chain_contains(requester_node_id, target_agent_id):
            return True
        if self._parent_chain_contains(target_agent_id, requester_node_id):
            return True

        requester_sibling_group = requester.get("sibling_group")
        return requester_sibling_group is not None and requester_sibling_group == target.get("sibling_group")

    def _can_contact_by_public_handle(self, requester_node_id: str, target_agent_id: str) -> bool:
        """Allow contact when the requester is a registered node and the target
        exposes a public handle. This is a routable contact path only; it never
        grants directory listing, transcript access, or wait-result ownership."""

        requester = self.get_agent(requester_node_id)
        target = self.get_agent(target_agent_id)
        if requester is None or target is None:
            return False
        if requester_node_id == target_agent_id:
            return True
        return self._agent_has_public_handle(target)

    @staticmethod
    def _agent_has_public_handle(agent: dict[str, Any]) -> bool:
        if agent.get("role") not in {"agent", "session"}:
            return False
        handle = agent.get("agent_handle")
        agent_id = agent.get("id")
        return isinstance(handle, str) and bool(handle) and handle != agent_id

    def _parent_chain_contains(self, agent_id: str, target_agent_id: str) -> bool:
        visited: set[str] = set()
        current = agent_id

        while isinstance(current, str) and current not in visited:
            visited.add(current)
            row = self.get_agent(current)
            if row is None:
                return False

            parent_id = row.get("parent_id")
            if not isinstance(parent_id, str) or not parent_id.strip():
                return False
            if parent_id == target_agent_id:
                return True
            current = parent_id

        return False

    def get_root_agent_directory(
        self,
        *,
        requester_node_id: str,
        awaitable: bool = False,
    ) -> list[dict[str, Any]]:
        """List non-session agents under the caller's root with safe status metadata."""

        root_id = self.resolve_agent_root(requester_node_id)
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
                a.agent_type,
                a.run_kind,
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
                END AS awaitable,
                r.spec_json AS spec_json
            FROM scoped_agents AS s
            INNER JOIN agents AS a ON a.id = s.id
            LEFT JOIN runs AS r ON r.id = a.current_run_id
            WHERE a.role != 'session'
              AND (a.agent_type IS NULL OR a.agent_type != 'ask')
            {awaitable_filter}
            ORDER BY a.depth ASC, a.id ASC
            """

        params: tuple[Any, ...] = (root_id, requester_node_id)
        if awaitable:
            params = (root_id, requester_node_id, requester_node_id)

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()

        directory: list[dict[str, Any]] = []
        for row in rows:
            task: str | None = None
            spec_json = row["spec_json"]
            if isinstance(spec_json, str):
                try:
                    spec = json.loads(spec_json)
                except json.JSONDecodeError:
                    spec = None
                if isinstance(spec, dict):
                    task = _preview_text(spec.get("task"))

            directory.append(
                {
                    "agent_id": row["agent_id"],
                    "agent_handle": row["agent_handle"],
                    "agent_type": row["agent_type"],
                    "run_kind": row["run_kind"],
                    "parent_id": row["parent_id"],
                    "role": row["role"],
                    "session_name": row["session_name"],
                    "depth": row["depth"],
                    "status": row["status"],
                    "awaitable": bool(row["awaitable"]),
                    "task": task,
                }
            )
        return directory

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
              AND a.role != 'session'
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
              AND a.role != 'session'
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

    def _read_task_cycles(self, agent_id: str) -> list[dict[str, Any]]:
        """Safely read task cycles for an internal agent id."""

        if not _is_valid_agent_id(agent_id):
            return []

        task_path = self.task_dir / f"{agent_id}.json"
        try:
            root = self.task_dir.resolve(strict=False)
            candidate = task_path.resolve(strict=False)
            if root != candidate.parent:
                return []

            metadata = os.lstat(task_path)
            if not os.path.isfile(task_path) or os.path.islink(task_path):
                return []
            if metadata.st_size > RUN_SUMMARY_TASK_LOG_MAX_BYTES:
                return []

            with task_path.open("r", encoding="utf-8") as file:
                parsed = json.load(file)
        except (OSError, json.JSONDecodeError):
            return []

        if not isinstance(parsed, list):
            return []
        return [cycle for cycle in parsed if isinstance(cycle, dict)]

    def _project_task_log(self, agent_id: str) -> dict[str, Any] | None:
        cycles = self._read_task_cycles(agent_id)
        active = next((cycle for cycle in cycles if cycle.get("active") is True), None)
        if active is None:
            return None

        raw_tasks = active.get("tasks")
        if not isinstance(raw_tasks, list):
            return None

        tasks: list[dict[str, Any]] = []
        current_task: dict[str, Any] | None = None
        deleted = 0
        completed = 0
        total = 0
        for index, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, dict):
                continue
            status = raw_task.get("status")
            if status not in {"pending", "active", "completed", "deleted"}:
                continue
            if status == "deleted":
                deleted += 1
                continue

            label = _display_text(raw_task.get("label"))
            if label is None:
                continue
            if status == "completed":
                completed += 1
            total += 1
            task_row = {"index": index, "label": label, "status": status}
            if len(tasks) < RUN_SUMMARY_TASK_PLAN_LIMIT:
                tasks.append(task_row)
            if status == "active" and current_task is None:
                current_task = {
                    **task_row,
                    "description": _display_text(raw_task.get("description")),
                    "notes": _display_text(raw_task.get("notes")),
                }

        return {
            "goal": _display_text(active.get("goal")),
            "progress": {
                "completed": completed,
                "deleted": deleted,
                "total": total,
            },
            "task_plan": tasks,
            "current_task": current_task,
        }

    def _project_recent_activity(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT seq, kind, payload_json, ts
                FROM run_events
                WHERE run_id = ?
                ORDER BY seq DESC
                LIMIT ?
                """,
                (run_id, RUN_SUMMARY_ACTIVITY_LIMIT),
            ).fetchall()

        activity: list[dict[str, Any]] = []
        for row in reversed(rows):
            kind = row["kind"]
            if kind not in _ACTIVITY_KINDS:
                continue
            event: dict[str, Any] = {
                "kind": kind,
                "seq": row["seq"],
                "timestamp": _display_text(row["ts"]),
            }
            payload: Any = {}
            try:
                payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                for key in _ACTIVITY_PAYLOAD_KEYS:
                    value = payload.get(key)
                    if key == "isError":
                        if isinstance(value, bool):
                            event[key] = value
                    elif isinstance(value, str):
                        event[key] = _display_text(value)
                    elif isinstance(value, int | float) and not isinstance(value, bool):
                        event[key] = value
            activity.append({key: value for key, value in event.items() if value is not None})
        return activity

    def _project_skills(self, run_id: str | None) -> list[dict[str, Any]]:
        if not run_id:
            return []

        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT seq, payload_json, ts
                FROM run_events
                WHERE run_id = ?
                  AND kind = 'tool_call'
                ORDER BY seq ASC
                """,
                (run_id,),
            ).fetchall()

        skills: dict[str, dict[str, Any]] = {}
        for row in rows:
            payload: Any = {}
            try:
                payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict) or payload.get("toolName") != "skill":
                continue

            name = _display_text(payload.get("skillName"))
            snippet = payload.get("snippet")
            if not name and isinstance(snippet, str) and snippet.startswith("skill "):
                name = _display_text(snippet.removeprefix("skill "))
            if not name:
                continue

            skill = skills.setdefault(
                name,
                {
                    "name": name,
                    "count": 0,
                    "last_seq": row["seq"],
                    "last_timestamp": _display_text(row["ts"]),
                },
            )
            skill["count"] += 1
            skill["last_seq"] = row["seq"]
            skill["last_timestamp"] = _display_text(row["ts"])

        return sorted(skills.values(), key=lambda skill: skill["last_seq"], reverse=True)[:RUN_SUMMARY_SKILLS_LIMIT]

    def get_run_messages(
        self,
        root_id: str,
        *,
        agent_handle: str,
        limit: int = RUN_MESSAGES_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        """Return latest visible assistant messages for one scoped agent."""

        safe_limit = max(0, min(limit, RUN_MESSAGES_MAX_LIMIT))
        messages: list[dict[str, Any]] = []

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
            agent_row = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    a.agent_handle,
                    r.id AS run_id,
                    r.result,
                    r.ended_at
                FROM agents AS a
                INNER JOIN scoped_agents AS s ON s.id = a.id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE a.agent_handle = ?
                  AND a.role != 'session'
                LIMIT 1
                """,
                (root_id, agent_handle),
            ).fetchone()

            if agent_row is not None and agent_row["run_id"] and safe_limit:
                rows = connection.execute(
                    """
                    SELECT seq, payload_json, ts
                    FROM run_events
                    WHERE run_id = ?
                      AND kind = 'assistant_output'
                    ORDER BY seq DESC
                    LIMIT ?
                    """,
                    (agent_row["run_id"], safe_limit),
                ).fetchall()

                for row in reversed(rows):
                    payload: Any = {}
                    try:
                        payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else {}
                    except json.JSONDecodeError:
                        payload = {}
                    if not isinstance(payload, dict):
                        continue
                    text = _message_text(payload.get("text"))
                    if text is None:
                        continue
                    messages.append(
                        {
                            "kind": "assistant_output",
                            "seq": row["seq"],
                            "timestamp": _display_text(row["ts"]),
                            "label": _display_text(payload.get("label")),
                            "text": text,
                        }
                    )

                result_text = _message_text(agent_row["result"])
                if result_text is not None and (not messages or messages[-1]["text"] != result_text):
                    messages.append(
                        {
                            "kind": "agent_result",
                            "seq": None,
                            "timestamp": _display_text(agent_row["ended_at"]),
                            "label": "result",
                            "text": result_text,
                        }
                    )

        return {
            "root_id": root_id,
            "agent_handle": agent_handle,
            "messages": messages[-safe_limit:] if safe_limit else [],
        }

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

            agent_rows = connection.execute(
                f"""
                {recursive_scope}
                SELECT
                    a.id AS agent_id,
                    a.agent_handle,
                    a.agent_type,
                    a.model,
                    a.role,
                    a.session_name,
                    r.id AS run_id,
                    CASE
                        WHEN r.status IN ('pending', 'running', 'completed', 'failed') THEN r.status
                        ELSE 'idle'
                    END AS status,
                    r.result,
                    r.error,
                    r.exit_code,
                    r.created_at,
                    r.started_at,
                    r.ended_at
                FROM agents AS a
                INNER JOIN scoped_agents AS s ON s.id = a.id
                LEFT JOIN runs AS r ON r.id = a.current_run_id
                WHERE a.role != 'session'
                ORDER BY COALESCE(r.created_at, a.created_at) DESC, a.agent_handle ASC
                LIMIT ?
                """,
                (root_id, safe_limit),
            ).fetchall()

        agents = [
            {
                "agent_handle": _display_text(row["agent_handle"]),
                "agent_id_short": _agent_id_short(row["agent_id"]),
                "agent_type": _display_text(row["agent_type"]),
                "model": _display_text(row["model"] or "default"),
                "role": _display_text(row["role"]),
                "session_name": _display_text(row["session_name"]),
                "status": row["status"],
                "result_preview": _preview_text(row["result"]),
                "error_preview": _preview_text(row["error"]),
                "exit_code": row["exit_code"],
                "created_at": _display_text(row["created_at"]),
                "started_at": _display_text(row["started_at"]),
                "ended_at": _display_text(row["ended_at"]),
                "task": self._project_task_log(row["agent_id"]),
                "recent_activity": self._project_recent_activity(row["run_id"]),
                "skills": self._project_skills(row["run_id"]),
            }
            for row in agent_rows
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
            "agents": agents,
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
