"""Signal-boundary integration tests for supervised ``bomp`` workspaces."""

from __future__ import annotations

import os
import pty
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_detached_entrypoint import (
    _git,
    _make_harness,
    _wait_for_path,
    _worktrees,
    _write_delayed_git,
)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group signal behavior")
@pytest.mark.parametrize("automatic", [False, True], ids=["explicit-detached", "automatic"])
@pytest.mark.parametrize("phase", ["creation", "cleanup"])
def test_bomp_defers_interrupt_during_owned_worktree_operation(
    tmp_path: Path,
    phase: str,
    *,
    automatic: bool,
) -> None:
    harness = _make_harness(tmp_path)
    mode = "automatic" if automatic else "detached"
    ready = tmp_path / f"{mode}-{phase}-ready"
    release = tmp_path / f"{mode}-{phase}-release"
    prefix = f"BOMP_{phase.upper()}"
    harness.environment.update({f"{prefix}_READY": str(ready), f"{prefix}_RELEASE": str(release)})
    if phase == "cleanup":
        real_git = shutil.which("git")
        assert real_git is not None
        _write_delayed_git(harness.fake_omp.parent / "git", real_git)
    entrypoint = Path(sys.executable).with_name("bomp")
    arguments = [str(entrypoint)]
    if not automatic:
        arguments.append("--detached")
    arguments.extend(("--cwd", str(harness.nested)))
    master, slave = pty.openpty()
    process = subprocess.Popen(
        arguments,
        cwd=harness.source.parent,
        env=harness.environment,
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    os.close(slave)

    try:
        _wait_for_path(ready)
        workspace = Path(ready.read_text())
        os.killpg(process.pid, signal.SIGINT)
        time.sleep(0.1)

        assert process.poll() is None
        assert workspace.is_dir()
        release.touch()
        _stdout, stderr = process.communicate(timeout=30)
    finally:
        os.close(master)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    assert process.returncode == 128 + signal.SIGINT, stderr
    assert not workspace.exists()
    assert workspace not in _worktrees(harness.source)
    assert "could not remove detached worktree" not in stderr
    if automatic:
        assert _git(harness.source, "for-each-ref", "refs/basecamp/omp/snapshots").stdout == ""


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group signal behavior")
def test_bomp_detached_does_not_clean_up_on_turn_interrupt(tmp_path: Path) -> None:
    harness = _make_harness(tmp_path)
    ready = tmp_path / "ready"
    interrupted = tmp_path / "interrupted"
    release = tmp_path / "release"
    harness.environment.update(
        {
            "BOMP_WAIT_FOR_RELEASE": "1",
            "BOMP_READY_MARKER": str(ready),
            "BOMP_INTERRUPT_MARKER": str(interrupted),
            "BOMP_RELEASE_MARKER": str(release),
        }
    )
    entrypoint = Path(sys.executable).with_name("bomp")
    process = subprocess.Popen(
        [str(entrypoint), "--detached", "--cwd", str(harness.nested)],
        cwd=harness.source.parent,
        env=harness.environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        _wait_for_path(ready)
        workspace = Path(ready.read_text())
        os.killpg(process.pid, signal.SIGINT)
        _wait_for_path(interrupted)

        assert process.poll() is None
        assert workspace.is_dir()
        assert workspace in _worktrees(harness.source)

        release.touch()
        _stdout, stderr = process.communicate(timeout=20)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    assert process.returncode == 0, stderr
    assert not workspace.exists()
    assert workspace not in _worktrees(harness.source)
