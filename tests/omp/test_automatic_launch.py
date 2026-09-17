"""End-to-end behavior for automatic canonical scratch placement."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from basecamp.omp import launcher


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_dirty_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("base\n")
    _git(root, "add", "tracked.txt")
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        "initial",
    )
    nested = root / "nested"
    nested.mkdir()
    (root / "tracked.txt").write_text("staged\n")
    _git(root, "add", "tracked.txt")
    (root / "tracked.txt").write_text("staged and unstaged\n")
    (root / "untracked.txt").write_text("untracked\n")
    (root / "intent.txt").write_text("intent\n")
    _git(root, "add", "-N", "intent.txt")
    return nested


def _fake_omp(path: Path) -> Path:
    path.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\n"
        "command = sys.argv[1:]\n"
        "raise SystemExit(subprocess.run(['git', *command], check=False).returncode)\n"
    )
    path.chmod(0o755)
    return path


def _extension(path: Path) -> Path:
    path.mkdir()
    (path / "package.json").write_text("{}")
    (path / "extension.ts").write_text("export default () => {}")
    return path


def test_automatic_launch_transfers_wip_uses_real_nested_cwd_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nested = _init_dirty_repo(source)
    extension = _extension(tmp_path / "omp-package")
    worktrees = tmp_path / "worktrees"
    sessions = tmp_path / "sessions"
    fake_omp = _fake_omp(tmp_path / "omp")
    source_status = _git(
        source,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    source_index = Path(
        _git(source, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.decode().strip()
    )
    source_index_bytes = source_index.read_bytes()
    observed: dict[str, object] = {}

    def supervise(argv: list[str], *, cwd: Path, environ: dict[str, str]) -> int:
        root = Path(_git(cwd, "rev-parse", "--show-toplevel").stdout.decode().strip())
        observed.update(argv=argv, cwd=cwd, root=root, environment=environ)
        observed["status"] = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        observed["content"] = (root / "tracked.txt").read_text()
        return 17

    monkeypatch.setattr(launcher, "supervise_omp", supervise)
    environment = {
        **os.environ,
        "OMP_WORKTREE_DIR": str(worktrees),
    }

    status = launcher._run_automatic_launch(
        ["--cwd", str(nested), "--session-dir", str(sessions), "prompt"],
        cwd=tmp_path,
        projects={},
        package=extension,
        omp_executable=str(fake_omp),
        environ=environment,
    )

    assert status == 17
    scratch = Path(observed["environment"]["BASECAMP_OMP_SCRATCH_ROOT"])
    assert observed["cwd"] == scratch / "nested"
    assert observed["root"] == scratch
    assert observed["content"] == "staged and unstaged\n"
    assert observed["status"] == source_status
    assert "--cwd" not in observed["argv"]
    assert observed["environment"]["BASECAMP_PROTECTED_ROOT"] == str(source.resolve())
    assert observed["environment"]["BASECAMP_OMP_INHERITED_WIP"] == "1"
    assert observed["argv"][-3:] == ["--session-dir", str(sessions), "prompt"]
    assert _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == source_status
    assert source_index.read_bytes() == source_index_bytes
    stderr = capsys.readouterr().err
    assert "Uncommitted work copied into scratch" in stderr
    assert f"temporary worktree {scratch}" in stderr
    assert not scratch.exists()
    assert _git(source, "for-each-ref", "--format=%(refname)", "refs/basecamp/omp/snapshots").stdout == b""


def test_automatic_launch_retains_execution_changes_and_releases_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    nested = _init_dirty_repo(source)
    extension = _extension(tmp_path / "omp-package")
    fake_omp = _fake_omp(tmp_path / "omp")
    observed: dict[str, Path] = {}

    def supervise(_argv: list[str], *, cwd: Path, environ: dict[str, str]) -> int:
        scratch = Path(environ["BASECAMP_OMP_SCRATCH_ROOT"])
        observed["scratch"] = scratch
        (scratch / "agent-change.txt").write_text("retain me\n")
        assert cwd == scratch / "nested"
        return 0

    monkeypatch.setattr(launcher, "supervise_omp", supervise)

    status = launcher._run_automatic_launch(
        ["--cwd", str(nested), "prompt"],
        cwd=tmp_path,
        projects={},
        package=extension,
        omp_executable=str(fake_omp),
        environ={**os.environ, "OMP_WORKTREE_DIR": str(tmp_path / "worktrees")},
    )

    scratch = observed["scratch"]
    assert status == 0
    assert (scratch / "agent-change.txt").read_text() == "retain me\n"
    assert not (source / "agent-change.txt").exists()
    assert _git(source, "for-each-ref", "--format=%(refname)", "refs/basecamp/omp/snapshots").stdout == b""
    assert f"retaining temporary worktree {scratch}" in capsys.readouterr().err
