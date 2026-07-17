"""Workstream-record RPCs the MCP tools and the ``workstream`` CLI call.

``create_workstream`` ensures a daemon is up (spawning one if needed) then POSTs
the record — the copilot staging path needs a live daemon, so this one may raise
:class:`DaemonError`. The reads (``get`` / ``list`` / ``list_sessions``) and the
mutations (``set_status`` / ``attach`` / ``delete``) are best-effort: they never
spawn and never raise, resolving a transport failure to ``None``/``False``/``[]``
so a daemon-down CLI degrades cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .paths import DaemonPaths, daemon_paths
from .spawn import ensure_daemon
from .transport import delete_json, get_json, post_json


@dataclass(frozen=True)
class WorkstreamCreateOutcome:
    """Result of a create POST: ``created`` on 201, ``slug_conflict`` on 409."""

    status: int
    body: Any

    @property
    def created(self) -> bool:
        return self.status == 201

    @property
    def slug_conflict(self) -> bool:
        return self.status == 409


def create_workstream(
    *,
    workstream_id: str,
    slug: str,
    label: str | None = None,
    repo: str | None = None,
    dossier_path: str | None = None,
    paths: DaemonPaths | None = None,
) -> WorkstreamCreateOutcome:
    """Ensure the daemon is running, then create a workstream record. May raise DaemonError."""

    resolved = paths or daemon_paths()
    socket = ensure_daemon(resolved)
    status, response = post_json(
        socket,
        "/workstreams",
        {
            "id": workstream_id,
            "slug": slug,
            "label": label,
            "repo": repo,
            "dossier_path": dossier_path,
        },
    )
    return WorkstreamCreateOutcome(status=status, body=response)


def get_workstream(identifier: str, *, paths: DaemonPaths | None = None) -> dict[str, Any] | None:
    """Best-effort fetch a workstream by id or slug; ``None`` if absent or daemon down."""

    return _get(f"/workstreams/{identifier}", paths=paths)


def list_workstreams(
    *,
    repo: str | None = None,
    status: str | None = None,
    paths: DaemonPaths | None = None,
) -> list[dict[str, Any]]:
    """Best-effort list workstreams; empty list if the daemon is unreachable."""

    resolved = paths or daemon_paths()
    params = {k: v for k, v in (("repo", repo), ("status", status)) if v is not None}
    try:
        code, body = get_json(str(resolved.socket), "/workstreams", params=params or None)
    except (httpx.HTTPError, OSError):
        return []
    if code == 200 and isinstance(body, dict) and isinstance(body.get("workstreams"), list):
        return body["workstreams"]
    return []


def list_workstream_sessions(identifier: str, *, paths: DaemonPaths | None = None) -> list[dict[str, Any]]:
    """Best-effort list the sessions attached to a workstream; empty if none or daemon down."""

    resolved = paths or daemon_paths()
    try:
        code, body = get_json(str(resolved.socket), f"/workstreams/{identifier}/sessions")
    except (httpx.HTTPError, OSError):
        return []
    if code == 200 and isinstance(body, dict) and isinstance(body.get("sessions"), list):
        return body["sessions"]
    return []


def set_workstream_status(identifier: str, status: str, *, paths: DaemonPaths | None = None) -> bool:
    """Best-effort set a workstream's status; ``False`` if not updated or daemon down."""

    resolved = paths or daemon_paths()
    try:
        code, body = post_json(str(resolved.socket), f"/workstreams/{identifier}/status", {"status": status})
    except (httpx.HTTPError, OSError):
        return False
    return code == 200 and isinstance(body, dict) and bool(body.get("updated"))


def attach_workstream_session(
    identifier: str,
    session_id: str,
    *,
    repo: str | None = None,
    worktree_path: str | None = None,
    paths: DaemonPaths | None = None,
) -> bool:
    """Best-effort attach a session (agent) to a workstream; ``False`` on failure or daemon down."""

    resolved = paths or daemon_paths()
    try:
        code, body = post_json(
            str(resolved.socket),
            f"/workstreams/{identifier}/attach",
            {"session_id": session_id, "repo": repo, "worktree_path": worktree_path},
        )
    except (httpx.HTTPError, OSError):
        return False
    return code == 200 and isinstance(body, dict) and bool(body.get("attached"))


def delete_workstream(identifier: str, *, paths: DaemonPaths | None = None) -> bool:
    """Best-effort delete a workstream record (used to roll back a failed create)."""

    resolved = paths or daemon_paths()
    try:
        code, _body = delete_json(str(resolved.socket), f"/workstreams/{identifier}")
    except (httpx.HTTPError, OSError):
        return False
    return code == 200


def _get(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    paths: DaemonPaths | None = None,
) -> dict[str, Any] | None:
    resolved = paths or daemon_paths()
    try:
        code, body = get_json(str(resolved.socket), path, params=params)
    except (httpx.HTTPError, OSError):
        return None
    return body if code == 200 and isinstance(body, dict) else None
