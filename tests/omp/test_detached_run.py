"""Tests for disposable OMP worktree execution and cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.omp import detached_run
from basecamp.omp.detached_plan import DetachedArguments, DetachedPlan, GitSource


def _plan(tmp_path: Path, *, profile: str | None = None, relative_cwd: str = ".") -> DetachedPlan:
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    return DetachedPlan(
        arguments=DetachedArguments(
            source_cwd=source,
            omp_args=("--mode=rpc",),
            profile=profile,
        ),
        source=GitSource(
            root=source,
            relative_cwd=Path(relative_cwd),
            head="1234567890abcdef",
        ),
        worktree_base=tmp_path / "worktrees",
    )


def test_create_workspace_invokes_public_omp_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path, profile="review", relative_cwd="packages/demo")
    captured: dict[str, object] = {}

    def fake_mkdtemp(*, prefix: str, **kwargs: Path) -> str:
        base = kwargs["dir"]
        captured.update(prefix=prefix, base=base)
        reserved = base / f"{prefix}abcdef12"
        reserved.mkdir()
        return str(reserved)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="clone fallback warning\n")

    monkeypatch.setattr(detached_run.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(detached_run, "_run_captured", fake_run)
    environment = {"HOME": str(tmp_path / "home")}

    workspace = detached_run.create_workspace(plan, omp_executable="/tools/omp", environ=environment)

    assert workspace.path == tmp_path / "worktrees" / "bomp-source-1234567-abcdef12"
    assert workspace.launch_cwd == workspace.path / "packages" / "demo"
    assert workspace.launch_cwd.is_dir()
    assert workspace.warnings == ("clone fallback warning",)
    assert captured["command"] == [
        "/tools/omp",
        "--profile",
        "review",
        "worktree",
        "add",
        "--detach",
        "--quiet",
        str(workspace.path),
        "HEAD",
    ]
    assert captured["cwd"] == plan.source.root
    assert captured["environ"] == environment


def test_create_workspace_reports_omp_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)
    monkeypatch.setattr(
        detached_run,
        "_run_captured",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="creation failed\n"),
    )

    with pytest.raises(LauncherError, match="creation failed"):
        detached_run.create_workspace(plan, omp_executable="/tools/omp", environ={})


def test_create_workspace_removes_unregistered_partial_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan(tmp_path)

    def fail_after_writing(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] != "git":
            workspace = Path(command[-2])
            (workspace / "partial.txt").write_text("partial")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="creation failed\n")

    monkeypatch.setattr(detached_run, "_run_captured", fail_after_writing)

    with pytest.raises(LauncherError, match="creation failed"):
        detached_run.create_workspace(plan, omp_executable="/tools/omp", environ={})

    assert list(plan.worktree_base.iterdir()) == []


def test_supervise_omp_uses_requested_cwd_environment_and_status(tmp_path: Path) -> None:
    capture = tmp_path / "capture.txt"
    child = tmp_path / "child.py"
    child.write_text(
        "import os, pathlib, sys\n"
        "pathlib.Path(os.environ['CAPTURE']).write_text(os.getcwd() + '\\n' + '|'.join(sys.argv[1:]))\n"
        "raise SystemExit(23)\n"
    )
    launch_cwd = tmp_path / "worktree" / "nested"
    launch_cwd.mkdir(parents=True)
    environment = {**os.environ, "CAPTURE": str(capture)}

    status = detached_run.supervise_omp(
        [sys.executable, str(child), "unchanged argument", "--mode=rpc"],
        cwd=launch_cwd,
        environ=environment,
    )

    assert status == 23
    assert capture.read_text() == f"{launch_cwd}\nunchanged argument|--mode=rpc"


def test_supervise_omp_translates_signal_exit_to_shell_status(tmp_path: Path) -> None:
    child = tmp_path / "terminate.py"
    child.write_text("import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n")

    status = detached_run.supervise_omp(
        [sys.executable, str(child)],
        cwd=tmp_path,
        environ=os.environ,
    )

    assert status == 128 + signal.SIGTERM


def test_remove_workspace_targets_only_created_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(detached_run, "_run_captured", fake_run)
    source = tmp_path / "source repo"
    workspace = tmp_path / "managed worktree"

    failure = detached_run.remove_workspace(source, workspace)

    assert failure is None
    assert captured["command"] == [
        "git",
        "-C",
        str(source),
        "worktree",
        "remove",
        "--force",
        str(workspace),
    ]


def test_remove_workspace_returns_exact_recovery_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        detached_run,
        "_run_captured",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="worktree is locked\n"),
    )
    source = tmp_path / "source repo"
    workspace = tmp_path / "managed worktree"

    failure = detached_run.remove_workspace(source, workspace)

    assert failure is not None
    assert failure.detail == "worktree is locked"
    assert failure.recovery_command == (f"git -C '{source}' worktree remove --force '{workspace}'")


def test_report_cleanup_failure_names_residue_and_recovery(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    failure = detached_run.CleanupFailure(detail="locked", recovery_command="git targeted cleanup")

    detached_run.report_cleanup_failure(failure, workspace_path=workspace, stream=sys.stderr)

    assert capsys.readouterr().err == (
        f"bomp: warning: could not remove detached worktree {workspace}: locked\n"
        "bomp: warning: recover with: git targeted cleanup\n"
    )
