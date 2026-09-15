"""Creation, supervision, and cleanup for disposable OMP worktrees."""

from __future__ import annotations

import re
import shlex
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import TextIO

from basecamp.core.exceptions import LauncherError
from basecamp.omp.detached_plan import DetachedPlan

_COMMAND_TIMEOUT_SECONDS = 60
_NAME_CHARACTERS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class DetachedWorkspace:
    """OMP-created checkout and the directory used by its child session."""

    path: Path
    launch_cwd: Path
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CleanupFailure:
    """Actionable failure to remove one disposable checkout."""

    detail: str
    recovery_command: str


@dataclass
class DeferredSignals:
    """Termination signal deferred until an owned workspace is cleaned."""

    received: int | None = None

    @property
    def status(self) -> int | None:
        return 128 + self.received if self.received is not None else None


def create_workspace(
    plan: DetachedPlan,
    *,
    omp_executable: str,
    environ: Mapping[str, str],
) -> DetachedWorkspace:
    """Create the planned detached checkout through OMP's public CLI."""
    try:
        plan.worktree_base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        message = f"Could not create OMP worktree base {plan.worktree_base}: {exc}"
        raise LauncherError(message) from exc

    workspace_path = _reserve_workspace_path(plan)
    command = [omp_executable]
    if plan.arguments.profile is not None:
        command.extend(("--profile", plan.arguments.profile))
    command.extend(("worktree", "add", "--detach", "--quiet", str(workspace_path), "HEAD"))
    try:
        result = _run_captured(command, cwd=plan.source.root, environ=environ)
    except (OSError, subprocess.SubprocessError) as exc:
        failure = _cleanup_failed_creation(plan.source.root, workspace_path)
        suffix = _cleanup_suffix(failure)
        message = f"Could not create detached OMP worktree: {exc}{suffix}"
        raise LauncherError(message) from exc
    if result.returncode != 0:
        failure = _cleanup_failed_creation(plan.source.root, workspace_path)
        detail = result.stderr.strip() or f"exit status {_shell_status(result.returncode)}"
        suffix = _cleanup_suffix(failure)
        message = f"Could not create detached OMP worktree: {detail}{suffix}"
        raise LauncherError(message)

    launch_cwd = workspace_path / plan.source.relative_cwd
    try:
        launch_cwd.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        failure = remove_workspace(plan.source.root, workspace_path)
        suffix = _cleanup_suffix(failure)
        message = f"Could not prepare detached launch directory {launch_cwd}: {exc}{suffix}"
        raise LauncherError(message) from exc
    warnings = tuple(line for line in result.stderr.splitlines() if line)
    return DetachedWorkspace(path=workspace_path, launch_cwd=launch_cwd, warnings=warnings)


def supervise_omp(
    argv: Sequence[str],
    *,
    cwd: Path,
    environ: Mapping[str, str],
) -> int:
    """Run OMP on the inherited terminal until its final process exit."""
    try:
        process = subprocess.Popen(list(argv), cwd=cwd, env=dict(environ))
    except OSError as exc:
        message = f"Could not start OMP: {exc}"
        raise LauncherError(message) from exc

    with _supervisor_signals(process):
        try:
            returncode = _wait_for_child(process)
        except BaseException:
            _stop_child(process)
            raise
    return _shell_status(returncode)


def remove_workspace(source_root: Path, workspace_path: Path) -> CleanupFailure | None:
    """Force-remove only the initial checkout owned by this invocation."""
    command = ["git", "-C", str(source_root), "worktree", "remove", "--force", str(workspace_path)]
    try:
        result = _run_captured(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return CleanupFailure(detail=str(exc), recovery_command=shlex.join(command))
    if result.returncode == 0:
        return None
    detail = result.stderr.strip() or f"exit status {result.returncode}"
    return CleanupFailure(detail=detail, recovery_command=shlex.join(command))


@contextmanager
def defer_termination_signals() -> Iterator[DeferredSignals]:
    """Delay process termination across gaps between managed child commands."""
    state = DeferredSignals()
    previous: dict[signal.Signals, signal.Handlers] = {}

    def record(process_signal: int, _frame: FrameType | None) -> None:
        state.received = state.received or process_signal

    process_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGQUIT"):
        process_signals.append(signal.SIGQUIT)
    if hasattr(signal, "SIGHUP"):
        process_signals.append(signal.SIGHUP)
    try:
        for process_signal in process_signals:
            previous[process_signal] = signal.signal(process_signal, record)
        yield state
    finally:
        for process_signal, handler in previous.items():
            signal.signal(process_signal, handler)


def report_cleanup_failure(
    failure: CleanupFailure,
    *,
    workspace_path: Path,
    stream: TextIO,
) -> None:
    """Print the retained path and its exact targeted recovery command."""
    print(f"bomp: warning: could not remove detached worktree {workspace_path}: {failure.detail}", file=stream)
    print(f"bomp: warning: recover with: {failure.recovery_command}", file=stream)


def _reserve_workspace_path(plan: DetachedPlan) -> Path:
    repository = _NAME_CHARACTERS.sub("-", plan.source.root.name).strip("-._") or "repository"
    prefix = f"bomp-{repository}-{plan.source.head[:7]}-"
    try:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=plan.worktree_base))
    except OSError as exc:
        message = f"Could not reserve a detached worktree under {plan.worktree_base}: {exc}"
        raise LauncherError(message) from exc


def _cleanup_failed_creation(source_root: Path, workspace_path: Path) -> CleanupFailure | None:
    failure = remove_workspace(source_root, workspace_path)
    if failure is None or not workspace_path.exists():
        return None
    if (workspace_path / ".git").exists():
        return failure

    recovery = ["rm", "-rf", "--", str(workspace_path)]
    try:
        shutil.rmtree(workspace_path)
    except OSError as exc:
        detail = f"{failure.detail}; recursive cleanup failed: {exc}"
        return CleanupFailure(detail=detail, recovery_command=shlex.join(recovery))
    return None


def _cleanup_suffix(failure: CleanupFailure | None) -> str:
    if failure is None:
        return ""
    return f"; retained worktree; recover with: {failure.recovery_command}"


def _run_captured(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=None if environ is None else dict(environ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    with _supervisor_signals(process):
        try:
            stdout, stderr = process.communicate(timeout=_COMMAND_TIMEOUT_SECONDS)
        except BaseException:
            _stop_child(process)
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _wait_for_child(process: subprocess.Popen[bytes]) -> int:
    while True:
        try:
            return process.wait()
        except InterruptedError:
            continue


def _stop_child(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _shell_status(returncode: int) -> int:
    return 128 + abs(returncode) if returncode < 0 else returncode


@contextmanager
def _supervisor_signals(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
) -> Iterator[None]:
    previous: dict[signal.Signals, signal.Handlers] = {}

    def forward(process_signal: int, _frame: FrameType | None) -> None:
        if process.poll() is not None:
            return
        try:
            process.send_signal(process_signal)
        except ProcessLookupError:
            pass

    ignored = [signal.SIGINT]
    if hasattr(signal, "SIGQUIT"):
        ignored.append(signal.SIGQUIT)
    forwarded = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        forwarded.append(signal.SIGHUP)
    try:
        for process_signal in ignored:
            previous[process_signal] = signal.signal(process_signal, signal.SIG_IGN)
        for process_signal in forwarded:
            previous[process_signal] = signal.signal(process_signal, forward)
        yield
    finally:
        for process_signal, handler in previous.items():
            signal.signal(process_signal, handler)
