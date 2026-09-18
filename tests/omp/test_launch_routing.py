"""Placement tests for automatic bomp scratch launches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from basecamp.omp import launcher


class _Stdin:
    def __init__(self, *, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _init_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "initial",
        ],
        check=True,
    )
    return path


def _extension(path: Path) -> Path:
    path.mkdir()
    (path / "package.json").write_text("{}")
    (path / "extension.ts").write_text("export default () => {}")
    return path


def test_fresh_canonical_tty_launch_uses_automatic_scratch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _init_repo(tmp_path / "source")
    nested = repository / "nested"
    nested.mkdir()
    extension = _extension(tmp_path / "omp")
    captured: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "/tools/omp")
    monkeypatch.setattr(launcher.sys, "stdin", _Stdin(is_tty=True))
    monkeypatch.setattr(launcher, "_native_auto_resume_state", lambda *_args, **_kwargs: False)

    def run_detached(args: tuple[str, ...], **kwargs: object) -> int:
        captured["args"] = args
        captured.update(kwargs)
        return 23

    monkeypatch.setattr(launcher, "_run_detached_launch", run_detached)

    status = launcher.run_launch(
        ["--cwd", str(nested), "prompt"],
        cwd=tmp_path,
        projects={},
        extension_dir=extension,
        environ={"HOME": str(tmp_path)},
    )

    assert status == 23
    assert captured["args"] == ("--cwd", str(nested), "prompt")
    assert captured["implicit"] is True
    assert captured["cwd"] == tmp_path


def test_flagless_native_auto_resume_stays_in_the_recorded_session_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _init_repo(tmp_path / "source")
    extension = _extension(tmp_path / "omp")
    captured: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "/tools/omp")
    monkeypatch.setattr(launcher.sys, "stdin", _Stdin(is_tty=True))
    monkeypatch.setattr(launcher, "_native_auto_resume_state", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        launcher,
        "_run_detached_launch",
        lambda *_args, **_kwargs: pytest.fail("auto-resume must not create a scratch"),
    )
    monkeypatch.setattr(
        launcher.os,
        "execvpe",
        lambda file, args, environment: captured.update(file=file, args=args, environment=environment),
    )

    launcher.run_launch(
        [],
        cwd=repository,
        projects={},
        extension_dir=extension,
        environ={"HOME": str(tmp_path)},
    )

    assert captured["args"] == ["omp", "--extension", str(extension.resolve())]


def test_native_auto_resume_query_uses_the_active_profile_and_source_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(arguments=arguments, **kwargs)
        return subprocess.CompletedProcess(arguments, 0, '{"value": true}\n', "")

    monkeypatch.setattr(launcher.subprocess, "run", run)

    assert launcher._native_auto_resume_state(
        "/tools/omp",
        cwd=tmp_path,
        profile="review",
        environ={"HOME": str(tmp_path)},
    )
    assert captured["arguments"] == [
        "/tools/omp",
        "--profile",
        "review",
        "config",
        "get",
        "autoResume",
        "--json",
    ]
    assert captured["cwd"] == tmp_path


def test_linked_worktree_and_non_tty_canonical_launch_stay_direct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _init_repo(tmp_path / "source")
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "-q", "-b", "topic", str(linked)],
        check=True,
    )

    monkeypatch.setattr(launcher.sys, "stdin", _Stdin(is_tty=True))
    assert launcher._uses_automatic_scratch(repository, ())
    assert not launcher._uses_automatic_scratch(linked, ())

    monkeypatch.setattr(launcher.sys, "stdin", _Stdin(is_tty=False))
    assert not launcher._uses_automatic_scratch(repository, ())


def test_direct_flag_changes_placement_without_reaching_omp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _init_repo(tmp_path / "source")
    extension = _extension(tmp_path / "omp")
    captured: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "/tools/omp")
    monkeypatch.setattr(launcher.sys, "stdin", _Stdin(is_tty=True))

    def exec_omp(file: str, args: list[str], environment: dict[str, str]) -> None:
        captured.update(file=file, args=args, environment=environment)

    monkeypatch.setattr(launcher.os, "execvpe", exec_omp)

    launcher.run_launch(
        ["--direct", "--cwd", str(repository), "prompt"],
        cwd=tmp_path,
        projects={},
        extension_dir=extension,
        environ={"HOME": str(tmp_path)},
    )

    assert captured["file"] == "omp"
    assert captured["args"] == [
        "omp",
        "--extension",
        str(extension.resolve()),
        "--cwd",
        str(repository),
        "prompt",
    ]
    environment = captured["environment"]
    assert environment["HOME"] == str(tmp_path)
