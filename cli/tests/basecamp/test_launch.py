"""Tests for launching pi through basecamp."""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from basecamp.cli import launch
from basecamp.config import ProjectConfig
from basecamp.main import bpi
from click.testing import CliRunner


def test_project_launch_does_not_prompt_for_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fail_input(prompt: str = "") -> str:
        calls["prompted"] = prompt
        return ""

    def fake_execvp(command: str, args: list[str]) -> None:
        calls["exec"] = (command, args)
        raise SystemExit(0)

    monkeypatch.setattr(builtins, "input", fail_input)
    monkeypatch.setattr(launch, "validate_dirs", lambda _dirs: [tmp_path])
    monkeypatch.setattr(launch.os, "chdir", lambda path: calls.setdefault("cwd", path))
    monkeypatch.setattr(launch.os, "execvp", fake_execvp)

    project = ProjectConfig(dirs=["src/project"])

    try:
        launch.execute_launch("demo", {"demo": project})
    except SystemExit as err:
        assert err.code == 0

    assert "prompted" not in calls
    assert calls["cwd"] == tmp_path
    assert calls["exec"] == ("pi", ["pi", "--project", "demo"])


def fake_launch(*_args: object, **_kwargs: object) -> None:
    return None


def test_bpi_blocks_deprecated_label_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("basecamp.main.execute_launch", fake_launch)

    result = CliRunner().invoke(bpi, [".", "--label", "demo"])

    assert result.exit_code == 1
    assert "Flag '--label' is managed by basecamp" in result.output


def test_bpi_blocks_deprecated_label_short_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("basecamp.main.execute_launch", fake_launch)

    result = CliRunner().invoke(bpi, [".", "-l", "demo"])

    assert result.exit_code == 1
    assert "Flag '-l' is managed by basecamp" in result.output


def test_bpi_blocks_internal_worktree_dir_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("basecamp.main.execute_launch", fake_launch)

    result = CliRunner().invoke(bpi, [".", "--worktree-dir", "/tmp/worktree"])

    assert result.exit_code == 1
    assert "Flag '--worktree-dir' is managed by basecamp" in result.output
