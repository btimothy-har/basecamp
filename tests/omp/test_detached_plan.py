"""Tests for disposable OMP launch planning."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.omp import detached_plan


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "tracked.txt").write_text("initial\n")
    subprocess.run(["git", "-C", str(path), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
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
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--detached"], True),
        (["--model", "test", "--detached"], True),
        (["--plan", "--detached"], False),
        (["--unknown-boolean", "--detached"], True),
        (["--append-system-prompt", "--detached"], False),
        (["--unknown-string", "--detached"], True),
        (["--", "--detached"], False),
        (["prompt", "--", "--detached"], False),
        (["--detached=value"], False),
    ],
)
def test_is_detached_requested_respects_omp_token_boundaries(
    args: list[str],
    expected: object,
) -> None:
    assert detached_plan.is_detached_requested(args) == expected


def test_parse_detached_arguments_consumes_only_launcher_tokens(tmp_path: Path) -> None:
    nested = tmp_path / "repo" / "nested"
    nested.mkdir(parents=True)
    args = [
        "--model",
        "test-model",
        "--detached",
        "--cwd",
        str(nested),
        "unchanged prompt",
        "--profile=review",
        "--detached",
    ]

    result = detached_plan.parse_detached_arguments(tmp_path, args, home=tmp_path / "home")

    assert result.source_cwd == nested.resolve()
    assert result.omp_args == (
        "--model",
        "test-model",
        "unchanged prompt",
        "--profile=review",
    )
    assert result.profile == "review"


def test_parse_detached_arguments_uses_last_cwd_and_preserves_separator(tmp_path: Path) -> None:
    second = tmp_path / "second"
    result = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "--cwd=first", "--cwd", str(second), "--", "--cwd=literal", "--detached"],
        home=tmp_path / "home",
    )

    assert result.source_cwd == second.resolve()
    assert result.omp_args == ("--", "--cwd=literal", "--detached")


def test_parse_detached_arguments_honors_flag_looking_cwd_value(tmp_path: Path) -> None:
    result = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "--cwd", "--profile", "work"],
        home=tmp_path / "home",
    )

    assert result.source_cwd == (tmp_path / "--profile").resolve()
    assert result.omp_args == ("work",)
    assert result.profile is None


def test_parse_detached_arguments_ignores_swallowed_session_flag(tmp_path: Path) -> None:
    result = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "--system-prompt", "--resume", "prompt"],
        home=tmp_path / "home",
    )

    assert result.omp_args == ("--system-prompt", "--resume", "prompt")


def test_parse_detached_arguments_preserves_absolute_session_directory(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"

    result = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "--session-dir", str(session_dir)],
        home=tmp_path / "home",
    )

    assert result.omp_args == ("--session-dir", str(session_dir))


@pytest.mark.parametrize("args", [["--session-dir", "relative"], ["--session-dir=relative"], ["--session-dir"]])
def test_parse_detached_arguments_rejects_relative_session_directory(tmp_path: Path, args: list[str]) -> None:
    with pytest.raises(LauncherError, match="requires --session-dir to use an absolute path"):
        detached_plan.parse_detached_arguments(tmp_path, ["--detached", *args], home=tmp_path / "home")


@pytest.mark.parametrize(
    "args",
    [
        ["--detached", "--continue"],
        ["--detached", "-c"],
        ["--detached", "--resume", "abc"],
        ["--detached", "--resume=abc"],
        ["--detached", "-r", "abc"],
        ["--detached", "--session", "abc"],
        ["--detached", "--fork", "abc"],
        ["--detached", "--from-claude"],
        ["--detached", "--from-codex"],
    ],
)
def test_parse_detached_arguments_rejects_existing_session_sources(
    tmp_path: Path,
    args: list[str],
) -> None:
    with pytest.raises(LauncherError, match="Detached mode starts a new session"):
        detached_plan.parse_detached_arguments(tmp_path, args, home=tmp_path / "home")


@pytest.mark.parametrize("command", ["config", "worktree", "wt", "update", "models", "help"])
def test_parse_detached_arguments_rejects_management_commands(
    tmp_path: Path,
    command: str,
) -> None:
    with pytest.raises(LauncherError, match="only starts OMP sessions"):
        detached_plan.parse_detached_arguments(
            tmp_path,
            ["--model", "test", "--detached", command],
            home=tmp_path / "home",
        )


def test_parse_detached_arguments_allows_explicit_launch_and_literal_management_word(tmp_path: Path) -> None:
    launched = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "launch", "config"],
        home=tmp_path / "home",
    )
    literal = detached_plan.parse_detached_arguments(
        tmp_path,
        ["--detached", "--", "config"],
        home=tmp_path / "home",
    )

    assert launched.omp_args == ("launch", "config")
    assert literal.omp_args == ("--", "config")


@pytest.mark.parametrize("args", [["--detached", "--cwd"], ["--detached", "--profile"], ["--detached", "--profile="]])
def test_parse_detached_arguments_rejects_missing_values(tmp_path: Path, args: list[str]) -> None:
    with pytest.raises(LauncherError, match="requires"):
        detached_plan.parse_detached_arguments(tmp_path, args, home=tmp_path / "home")


def test_resolve_git_source_preserves_nested_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    nested = repo / "packages" / "demo"
    expected_head = _init_repo(repo)
    nested.mkdir(parents=True)

    source = detached_plan.resolve_git_source(nested)

    assert source.root == repo.resolve()
    assert source.relative_cwd == Path("packages/demo")
    assert source.head == expected_head


@pytest.mark.parametrize("dirty_path", ["tracked.txt", "untracked.txt"])
def test_resolve_git_source_rejects_dirty_checkout(tmp_path: Path, dirty_path: str) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / dirty_path).write_text("changed\n")

    with pytest.raises(LauncherError, match="requires a clean source checkout"):
        detached_plan.resolve_git_source(repo)


def test_resolve_git_source_rejects_non_repository(tmp_path: Path) -> None:
    with pytest.raises(LauncherError, match="Could not inspect Git checkout"):
        detached_plan.resolve_git_source(tmp_path)


def test_resolve_worktree_base_prefers_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        message = "OMP config must not run when the environment overrides the base"
        raise AssertionError(message)

    monkeypatch.setattr(detached_plan.subprocess, "run", fail_run)

    result = detached_plan.resolve_worktree_base(
        "/bin/omp",
        source_cwd=tmp_path,
        profile=None,
        environ={"OMP_WORKTREE_DIR": "~/managed"},
        home=tmp_path / "home",
    )

    assert result == (tmp_path / "home" / "managed").resolve()


def test_resolve_worktree_base_reads_profile_and_project_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        payload = {"key": "worktree.base", "value": "~/configured", "type": "string"}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(detached_plan.subprocess, "run", fake_run)
    environment = {"HOME": str(tmp_path / "home")}

    result = detached_plan.resolve_worktree_base(
        "/tools/omp",
        source_cwd=tmp_path,
        profile="review",
        environ=environment,
        home=tmp_path / "home",
    )

    assert result == (tmp_path / "home" / "configured").resolve()
    assert captured["command"] == [
        "/tools/omp",
        "--profile",
        "review",
        "config",
        "get",
        "worktree.base",
        "--json",
    ]
    assert captured["cwd"] == tmp_path
    assert captured["env"] == environment


@pytest.mark.parametrize(
    ("payload", "expected_suffix"),
    [
        ({"key": "worktree.base", "type": "string"}, ".omp/wt"),
        ({"key": "worktree.base", "value": "relative/path"}, ".omp/wt"),
        ({"key": "worktree.base", "value": "/absolute/worktrees"}, "/absolute/worktrees"),
    ],
)
def test_resolve_worktree_base_falls_back_for_unset_or_relative_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, str],
    expected_suffix: str,
) -> None:
    def fake_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(detached_plan.subprocess, "run", fake_run)

    result = detached_plan.resolve_worktree_base(
        "/bin/omp",
        source_cwd=tmp_path,
        profile=None,
        environ={},
        home=tmp_path / "home",
    )

    expected = Path(expected_suffix) if expected_suffix.startswith("/") else tmp_path / "home" / expected_suffix
    assert result == expected


def test_resolve_worktree_base_uses_named_profile_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {"key": "worktree.base", "type": "string"}
    monkeypatch.setattr(
        detached_plan.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr=""),
    )

    result = detached_plan.resolve_worktree_base(
        "/bin/omp",
        source_cwd=tmp_path,
        profile="review",
        environ={},
        home=tmp_path / "home",
    )

    assert result == (tmp_path / "home" / ".omp" / "profiles" / "review" / "wt").resolve()


def test_resolve_worktree_base_uses_existing_xdg_profile_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {"key": "worktree.base", "type": "string"}
    monkeypatch.setattr(
        detached_plan.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr=""),
    )
    xdg_root = tmp_path / "xdg" / "omp" / "profiles" / "review"
    xdg_root.mkdir(parents=True)

    result = detached_plan.resolve_worktree_base(
        "/bin/omp",
        source_cwd=tmp_path,
        profile=None,
        environ={"OMP_PROFILE": "review", "XDG_DATA_HOME": str(tmp_path / "xdg")},
        home=tmp_path / "home",
    )

    assert result == xdg_root / "wt"


def test_resolve_worktree_base_reports_config_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        detached_plan.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args[0], 1, stdout="", stderr="invalid profile\n"),
    )

    with pytest.raises(LauncherError, match="invalid profile"):
        detached_plan.resolve_worktree_base(
            "/bin/omp",
            source_cwd=tmp_path,
            profile=None,
            environ={},
            home=tmp_path / "home",
        )


def test_plan_detached_launch_rejects_worktree_base_inside_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setattr(
        detached_plan,
        "resolve_worktree_base",
        lambda *_args, **_kwargs: repo / "managed",
    )

    with pytest.raises(LauncherError, match="worktree base to be outside"):
        detached_plan.plan_detached_launch(
            repo,
            ["--detached"],
            omp_executable="/bin/omp",
            environ={},
            home=tmp_path / "home",
        )


def test_plan_detached_launch_combines_validated_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    nested = repo / "nested"
    _init_repo(repo)
    nested.mkdir()
    base = tmp_path / "worktrees"

    def fake_resolve_worktree_base(*_args: object, **_kwargs: object) -> Path:
        return base

    monkeypatch.setattr(detached_plan, "resolve_worktree_base", fake_resolve_worktree_base)

    result = detached_plan.plan_detached_launch(
        tmp_path,
        ["--detached", "--cwd", str(nested), "--mode=rpc"],
        omp_executable="/bin/omp",
        environ={},
        home=tmp_path / "home",
    )

    assert result.arguments.omp_args == ("--mode=rpc",)
    assert result.source.root == repo.resolve()
    assert result.source.relative_cwd == Path("nested")
    assert result.worktree_base == base
