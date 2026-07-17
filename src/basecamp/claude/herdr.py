"""Open a workstream worktree in a Herdr pane (Python parallel of the Pi adapter).

Best-effort by design: a failed or absent ``herdr`` never breaks staging — the
record and worktree are already valid, so a pane failure is reported and the user
opens the pane by hand. Ports the Pi ``herdr.ts`` eligibility predicate verbatim
and shells out to the ``herdr`` CLI (a plain PATH binary).
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field

_HERDR_OPEN_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class HerdrResult:
    """Outcome of a Herdr pane open: ``opened`` | ``skipped`` | ``failed``."""

    status: str
    message: str
    reason: str | None = None
    args: tuple[str, ...] = field(default_factory=tuple)


def _agent_depth(env: Mapping[str, str]) -> int:
    raw = env.get("BASECAMP_AGENT_DEPTH")
    if raw is None or raw.strip() == "":
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 1


def herdr_skip_reason(env: Mapping[str, str], *, has_ui: bool = True) -> str | None:
    """Return a skip reason if a Herdr pane cannot/should not be opened, else ``None``.

    Ports ``shouldOpenWorkstreamInHerdr``: needs ``HERDR_ENV=1`` +
    ``HERDR_SOCKET_PATH`` + ``HERDR_PANE_ID``, a primary (depth-0) session, and a UI.
    """

    if env.get("HERDR_ENV") != "1":
        return "missing-herdr-env"
    if not env.get("HERDR_SOCKET_PATH"):
        return "missing-herdr-socket-path"
    if not env.get("HERDR_PANE_ID"):
        return "missing-herdr-pane-id"
    if _agent_depth(env) != 0:
        return "subagent"
    if has_ui is False:
        return "headless"
    return None


def build_open_args(
    *,
    worktree_path: str,
    label: str,
    workspace_cwd: str | None,
    env: Mapping[str, str],
) -> list[str] | None:
    """Build the ``herdr worktree open`` argv, or ``None`` if a required cwd is missing.

    Prefers ``--workspace <HERDR_WORKSPACE_ID>``; falls back to ``--cwd`` when the
    workspace id is absent. Caller has already checked :func:`herdr_skip_reason`.
    """

    args = ["worktree", "open"]
    workspace_id = env.get("HERDR_WORKSPACE_ID")
    if workspace_id:
        args += ["--workspace", workspace_id]
    else:
        if not workspace_cwd:
            return None
        args += ["--cwd", workspace_cwd]
    args += ["--path", worktree_path, "--label", label, "--no-focus", "--json"]
    return args


def open_pane(
    *,
    worktree_path: str,
    label: str,
    workspace_cwd: str | None,
    env: Mapping[str, str],
    has_ui: bool = True,
) -> HerdrResult:
    """Best-effort open ``worktree_path`` in a Herdr pane. Never raises."""

    reason = herdr_skip_reason(env, has_ui=has_ui)
    if reason is not None:
        return HerdrResult(status="skipped", message=f"Herdr pane open skipped: {reason}.", reason=reason)

    args = build_open_args(worktree_path=worktree_path, label=label, workspace_cwd=workspace_cwd, env=env)
    if args is None:
        return HerdrResult(status="skipped", message="Herdr pane open skipped: missing cwd.", reason="missing-cwd")

    try:
        result = subprocess.run(
            ["herdr", *args],
            capture_output=True,
            text=True,
            timeout=_HERDR_OPEN_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return HerdrResult(status="skipped", message="Herdr pane open skipped: herdr not on PATH.", reason="no-herdr")
    except (OSError, subprocess.SubprocessError) as exc:
        return HerdrResult(status="failed", message=f"Herdr pane open failed: {exc}.", args=tuple(args))
    if result.returncode != 0:
        return HerdrResult(
            status="failed",
            message=f"Herdr pane open failed with exit code {result.returncode}.",
            args=tuple(args),
        )
    return HerdrResult(status="opened", message="Herdr pane opened.", args=tuple(args))
