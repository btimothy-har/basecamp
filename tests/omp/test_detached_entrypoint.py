"""Subprocess integration tests for the ``bomp --detached`` entrypoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Harness:
    repository_root: Path
    source: Path
    nested: Path
    worktree_base: Path
    capture: Path
    fake_omp: Path
    environment: dict[str, str]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> Path:
    nested = path / "packages" / "demo"
    nested.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "tracked.txt").write_text("source content\n")
    (path / ".gitignore").write_text("ignored.tmp\n")
    (nested / "context.txt").write_text("nested content\n")
    _git(path, "add", ".")
    _git(
        path,
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return nested


def _write_fake_omp(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            from __future__ import annotations

            import json
            import os
            import signal
            import subprocess
            import sys
            import time
            from pathlib import Path


            def record(kind: str, **details: object) -> None:
                event = {{"kind": kind, "argv": sys.argv, "cwd": os.getcwd(), **details}}
                with Path(os.environ["BOMP_CAPTURE"]).open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event) + "\\n")


            def git(*args: str) -> None:
                subprocess.run(["git", *args], check=True)


            def git_output(*args: str) -> str:
                return subprocess.run(
                    ["git", *args],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()


            command = sys.argv[1:]
            if command[:1] == ["--profile"]:
                command = command[2:]
            elif command and command[0].startswith("--profile="):
                command = command[1:]

            if command == ["config", "get", "worktree.base", "--json"]:
                record("config")
                print(json.dumps({{"key": "worktree.base", "value": os.environ["BOMP_WORKTREE_BASE"]}}))
                raise SystemExit(0)

            if len(command) == 6 and command[:4] == ["worktree", "add", "--detach", "--quiet"]:
                record("worktree-add", workspace=command[4])
                if creation_ready := os.environ.get("BOMP_CREATION_READY"):
                    signal.signal(signal.SIGINT, signal.SIG_DFL)
                    Path(creation_ready).write_text(command[4])
                    release = Path(os.environ["BOMP_CREATION_RELEASE"])
                    while not release.exists():
                        time.sleep(0.02)
                result = subprocess.run(["git", *command], check=False)
                raise SystemExit(result.returncode)

            root = Path(git_output("rev-parse", "--show-toplevel"))
            if os.environ.get("BOMP_WAIT_FOR_RELEASE"):
                def note_interrupt(_signal: int, _frame: object) -> None:
                    Path(os.environ["BOMP_INTERRUPT_MARKER"]).write_text("interrupted")

                signal.signal(signal.SIGINT, note_interrupt)
                Path(os.environ["BOMP_READY_MARKER"]).write_text(str(root))
                release = Path(os.environ["BOMP_RELEASE_MARKER"])
                while not release.exists():
                    time.sleep(0.02)

            mutations = set(filter(None, os.environ.get("BOMP_MUTATIONS", "").split(",")))
            if "detached-commit" in mutations:
                (root / "detached-commit.txt").write_text("detached commit\\n")
                git("-C", str(root), "add", "detached-commit.txt")
                git(
                    "-C",
                    str(root),
                    "-c",
                    "user.email=test@example.com",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-q",
                    "-m",
                    "detached change",
                )
            if "staged" in mutations:
                (root / "staged.txt").write_text("staged\\n")
                git("-C", str(root), "add", "staged.txt")
            if "unstaged" in mutations:
                (root / "tracked.txt").write_text("unstaged\\n")
            if "untracked" in mutations:
                (root / "untracked.txt").write_text("untracked\\n")
            if "ignored" in mutations:
                (root / "ignored.tmp").write_text("ignored\\n")

            status = git_output("-C", str(root), "status", "--porcelain=v1", "--untracked-files=all", "--ignored")
            head = git_output("-C", str(root), "rev-parse", "HEAD")
            record("session", root=str(root), status=status, head=head)
            raise SystemExit(int(os.environ.get("BOMP_EXIT_STATUS", "0")))
            """
        )
    )
    path.chmod(0o755)


def _write_delayed_git(path: Path, real_git: str) -> None:
    path.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import os
            import signal
            import subprocess
            import sys
            import time
            from pathlib import Path

            arguments = sys.argv[1:]
            if arguments[2:5] == ["worktree", "remove", "--force"]:
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                Path(os.environ["BOMP_CLEANUP_READY"]).write_text(arguments[-1])
                release = Path(os.environ["BOMP_CLEANUP_RELEASE"])
                while not release.exists():
                    time.sleep(0.02)
            raise SystemExit(subprocess.run([{real_git!r}, *arguments], check=False).returncode)
            """
        )
    )
    path.chmod(0o755)


def _make_harness(tmp_path: Path) -> _Harness:
    repository_root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    source = tmp_path / "source"
    nested = _init_repo(source)
    worktree_base = tmp_path / "omp-worktrees"
    capture = tmp_path / "omp-events.jsonl"

    config_dir = home / ".pi" / "basecamp"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "version": 1,
                "install_dir": str(repository_root),
                "projects": {},
            }
        )
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_omp = fake_bin / "omp"
    _write_fake_omp(fake_omp)

    environment = os.environ.copy()
    source_pythonpath = str(repository_root / "src")
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{source_pythonpath}{os.pathsep}{inherited_pythonpath}" if inherited_pythonpath else source_pythonpath
    )
    environment.pop("OMP_WORKTREE_DIR", None)
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "BOMP_CAPTURE": str(capture),
            "BOMP_WORKTREE_BASE": str(worktree_base),
        }
    )
    return _Harness(
        repository_root=repository_root,
        source=source,
        nested=nested,
        worktree_base=worktree_base,
        capture=capture,
        fake_omp=fake_omp,
        environment=environment,
    )


def _run_bomp(harness: _Harness, args: list[str]) -> subprocess.CompletedProcess[str]:
    entrypoint = Path(sys.executable).with_name("bomp")
    return subprocess.run(
        [str(entrypoint), *args],
        cwd=harness.source.parent,
        env=harness.environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _worktrees(source: Path) -> set[Path]:
    output = _git(source, "worktree", "list", "--porcelain").stdout
    return {
        Path(line.removeprefix("worktree ")).resolve() for line in output.splitlines() if line.startswith("worktree ")
    }


def test_bomp_detached_consumes_launcher_args_and_preserves_session_args(tmp_path: Path) -> None:
    harness = _make_harness(tmp_path)
    user_args = [
        "--model",
        "test-model",
        "--detached",
        "--cwd",
        str(harness.nested),
        "--profile",
        "review",
        "--thinking",
        "high",
        "unchanged prompt",
    ]

    result = _run_bomp(harness, user_args)

    assert result.returncode == 0, result.stderr
    events = _events(harness.capture)
    assert [event["kind"] for event in events] == ["config", "worktree-add", "session"]
    assert events[0] == {
        "kind": "config",
        "argv": [
            str(harness.fake_omp),
            "--profile",
            "review",
            "config",
            "get",
            "worktree.base",
            "--json",
        ],
        "cwd": str(harness.nested),
    }

    workspace = Path(str(events[1]["workspace"]))
    assert events[1]["argv"] == [
        str(harness.fake_omp),
        "--profile",
        "review",
        "worktree",
        "add",
        "--detach",
        "--quiet",
        str(workspace),
        _git(harness.source, "rev-parse", "HEAD").stdout.strip(),
    ]
    assert events[1]["cwd"] == str(harness.source)

    expected_session_args = [
        "--extension",
        str((harness.repository_root / "omp").resolve()),
        "--model",
        "test-model",
        "--profile",
        "review",
        "--thinking",
        "high",
        "unchanged prompt",
    ]
    assert events[2]["argv"] == [str(harness.fake_omp), *expected_session_args]
    assert events[2]["cwd"] == str(workspace / "packages" / "demo")
    assert "--no-session" not in expected_session_args
    assert not any(
        argument == "--session-dir" or argument.startswith("--session-dir=") for argument in expected_session_args
    )


def test_bomp_detached_removes_changed_workspace_and_propagates_status(tmp_path: Path) -> None:
    harness = _make_harness(tmp_path)
    unrelated = tmp_path / "unrelated-worktree"
    _git(harness.source, "worktree", "add", "--detach", "--quiet", str(unrelated), "HEAD")
    source_head = _git(harness.source, "rev-parse", "HEAD").stdout.strip()
    source_tracked = (harness.source / "tracked.txt").read_bytes()
    harness.environment.update(
        {
            "BOMP_EXIT_STATUS": "37",
            "BOMP_MUTATIONS": "detached-commit,staged,unstaged,untracked,ignored",
        }
    )

    result = _run_bomp(
        harness,
        ["--detached", "--cwd", str(harness.nested), "unchanged prompt"],
    )

    assert result.returncode == 37, result.stderr
    events = _events(harness.capture)
    session = events[-1]
    workspace = Path(str(session["root"]))
    assert workspace == Path(str(events[1]["workspace"])).resolve()
    assert workspace.parent == harness.worktree_base
    assert session["head"] != source_head
    assert set(str(session["status"]).splitlines()) == {
        " M tracked.txt",
        "A  staged.txt",
        "?? untracked.txt",
        "!! ignored.tmp",
    }
    assert not workspace.exists()
    assert workspace not in _worktrees(harness.source)
    assert unrelated.resolve() in _worktrees(harness.source)
    assert unrelated.is_dir()

    assert _git(harness.source, "rev-parse", "HEAD").stdout.strip() == source_head
    assert _git(harness.source, "status", "--porcelain=v1", "--untracked-files=all").stdout == ""
    assert (harness.source / "tracked.txt").read_bytes() == source_tracked
    assert not (harness.source / "detached-commit.txt").exists()
    assert not (harness.source / "staged.txt").exists()
    assert not (harness.source / "untracked.txt").exists()
    assert not (harness.source / "ignored.tmp").exists()


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    message = f"Timed out waiting for {path}"
    raise AssertionError(message)
