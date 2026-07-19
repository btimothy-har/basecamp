"""Tests for basecamp.claude.launch — the ``bcc`` interactive launcher.

Cover the pure command builder (argv, env block, scratch dir) and the imperative
``run_launch`` shell with ``os.execvp`` stubbed so no process is actually replaced.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from basecamp.claude import launch


def _init_repo(path: Path, origin: str | None = None, *, commit: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if origin is not None:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)
    if commit:
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=path,
            check=True,
        )


def _patch_template(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "system-prompt.md").write_text("HEADER\n{{ENVIRONMENT}}\nFOOTER", encoding="utf-8")
    monkeypatch.setattr(launch, "shipped_prompts_dir", lambda: prompts)


def test_build_launch_in_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")

    plan = launch.build_launch(str(repo), ["--resume", "x"])

    scratch = tmp_path / "scratch" / "acme" / "web-app"
    assert plan.argv[0] == "claude"
    assert plan.argv[1] == "--system-prompt-file"
    assert plan.argv[2] == str(plan.prompt_path)
    assert plan.argv[3:] == ["--resume", "x"]
    assert plan.prompt_path == scratch / ".bcc-system-prompt.md"

    prompt = plan.prompt
    assert "{{ENVIRONMENT}}" not in prompt
    assert prompt.startswith("HEADER\n")
    assert prompt.endswith("\nFOOTER")
    assert "Git repository: Yes" in prompt
    assert "acme/web-app" in prompt  # remote
    assert "Current branch:" in prompt
    assert f"Working directory: {repo}" in prompt

    assert plan.env["BASECAMP_REPO"] == "acme/web-app"
    assert plan.env["BASECAMP_SCRATCH_DIR"] == str(scratch)
    assert plan.scratch_dir == scratch


def test_build_launch_outside_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    plain = tmp_path / "plain-dir"
    plain.mkdir()

    plan = launch.build_launch(str(plain), [])

    assert "Git repository: No" in plan.prompt
    assert "BASECAMP_REPO" not in plan.env
    assert plan.scratch_dir == tmp_path / "scratch" / "plain-dir"


def test_build_launch_reports_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    repo = tmp_path / "repo"
    _init_repo(repo)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feature"], cwd=repo, check=True)

    prompt = launch.build_launch(str(wt), []).prompt

    assert f"Active worktree: {wt.resolve()}" in prompt
    assert f"Protected checkout: {repo.resolve()}" in prompt


def test_run_launch_hands_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(launch.shutil, "which", lambda _cmd: "/usr/bin/claude")
    env_copy = dict(os.environ)
    monkeypatch.setattr(launch.os, "environ", env_copy)

    captured: dict[str, object] = {}

    def fake_execvp(file: str, args: list[str]) -> None:
        captured["file"] = file
        captured["args"] = args

    monkeypatch.setattr(launch.os, "execvp", fake_execvp)

    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web.git")
    launch.run_launch(["--continue"], cwd=str(repo))

    scratch = tmp_path / "scratch" / "acme" / "web"
    assert captured["file"] == "claude"
    assert captured["args"][0] == "claude"  # type: ignore[index]
    assert captured["args"][1] == "--system-prompt-file"  # type: ignore[index]
    assert captured["args"][-1] == "--continue"  # type: ignore[index]
    assert scratch.is_dir()

    prompt_file = scratch / ".bcc-system-prompt.md"
    assert prompt_file.is_file()
    assert "Git repository: Yes" in prompt_file.read_text(encoding="utf-8")
    assert env_copy["BASECAMP_SCRATCH_DIR"] == str(scratch)
    assert env_copy["BASECAMP_REPO"] == "acme/web"


def test_run_launch_clears_stale_repo_outside_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(launch.shutil, "which", lambda _cmd: "/usr/bin/claude")
    monkeypatch.setattr(launch.os, "execvp", lambda _file, _args: None)

    env_copy = dict(os.environ)
    env_copy["BASECAMP_REPO"] = "acme/inherited"  # leaked from a parent session
    monkeypatch.setattr(launch.os, "environ", env_copy)

    plain = tmp_path / "plain-dir"
    plain.mkdir()
    launch.run_launch([], cwd=str(plain))

    assert "BASECAMP_REPO" not in env_copy


def test_run_launch_clears_inherited_worktree_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(launch, "SCRATCH_ROOT", tmp_path / "scratch")
    monkeypatch.setattr(launch.shutil, "which", lambda _cmd: "/usr/bin/claude")
    monkeypatch.setattr(launch.os, "execvp", lambda _file, _args: None)

    env_copy = dict(os.environ)
    env_copy["BASECAMP_WORKTREE_LABEL"] = "wt-user/foo"  # leaked from a parent worktree session
    env_copy["BASECAMP_WORKTREE_DIR"] = "/somewhere/else"
    monkeypatch.setattr(launch.os, "environ", env_copy)

    repo = tmp_path / "repo"  # even a valid repo launch must drop stale worktree vars
    _init_repo(repo, "https://github.com/acme/web.git")
    launch.run_launch([], cwd=str(repo))

    assert "BASECAMP_WORKTREE_LABEL" not in env_copy
    assert "BASECAMP_WORKTREE_DIR" not in env_copy
    assert env_copy["BASECAMP_REPO"] == "acme/web"


def test_run_launch_missing_claude(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(launch.shutil, "which", lambda _cmd: None)
    with pytest.raises(SystemExit):
        launch.run_launch([], cwd=str(tmp_path))
