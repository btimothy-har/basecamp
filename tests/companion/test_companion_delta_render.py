"""Tests for the delta-backed diff renderer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rich.text import Text

from basecamp.companion import delta_render
from basecamp.companion.delta_render import delta_path, render_file_diff
from basecamp.companion.diff import FileStatus


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one committed file modified in the working tree."""

    _run(tmp_path, "init", "-q")
    _run(tmp_path, "config", "user.email", "t@t.test")
    _run(tmp_path, "config", "user.name", "t")
    target = tmp_path / "sample.py"
    target.write_text("def a():\n    return 1\n")
    _run(tmp_path, "add", "-A")
    _run(tmp_path, "commit", "-q", "-m", "init")
    target.write_text("def a():\n    return 2\n")
    return tmp_path


def _clear_cache() -> None:
    delta_path.cache_clear()


class TestRenderFileDiff:
    """render_file_diff behavior across delta availability and diff scopes."""

    def test_returns_none_when_delta_absent(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_cache()
        monkeypatch.setattr(delta_render.shutil, "which", lambda _name: None)
        result = render_file_diff(
            cwd=repo,
            base_commit="HEAD",
            file=FileStatus(path="sample.py", status="modified"),
            mode="uncommitted",
            width=100,
        )
        assert result is None
        _clear_cache()

    def test_returns_none_for_empty_diff(self, repo: Path) -> None:
        _clear_cache()
        if delta_path() is None:
            pytest.skip("delta binary not installed")
        # An unchanged file yields no diff -> None (fall back to built-in renderer).
        result = render_file_diff(
            cwd=repo,
            base_commit="HEAD",
            file=FileStatus(path="does-not-exist.py", status="modified"),
            mode="uncommitted",
            width=100,
        )
        assert result is None

    def test_renders_word_level_diff_when_delta_present(self, repo: Path) -> None:
        _clear_cache()
        if delta_path() is None:
            pytest.skip("delta binary not installed")
        result = render_file_diff(
            cwd=repo,
            base_commit="HEAD",
            file=FileStatus(path="sample.py", status="modified"),
            mode="uncommitted",
            width=120,
        )
        assert isinstance(result, Text)
        # Both sides of the change should appear in the captured render.
        assert "return" in result.plain
        # delta emitted styling that Rich parsed into spans.
        assert result.spans

    def test_fake_delta_is_invoked_with_forcing_flags(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The delta invocation must force width + ansi fill for non-tty capture."""

        _clear_cache()
        monkeypatch.setattr(delta_render, "delta_path", lambda: "/usr/bin/delta")
        captured: dict[str, list[str]] = {}
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
            if cmd and cmd[0] == "/usr/bin/delta":
                captured["cmd"] = cmd
                return subprocess.CompletedProcess(cmd, 0, stdout="\x1b[31mx\x1b[0m", stderr="")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(delta_render.subprocess, "run", fake_run)
        result = render_file_diff(
            cwd=repo,
            base_commit="HEAD",
            file=FileStatus(path="sample.py", status="modified"),
            mode="uncommitted",
            width=90,
        )
        assert isinstance(result, Text)
        assert "--width" in captured["cmd"]
        assert "90" in captured["cmd"]
        assert "--line-fill-method" in captured["cmd"]
        assert "--side-by-side" in captured["cmd"]


class TestGitDiffRefs:
    """The git ref selection must mirror file_diff_lines scopes."""

    def test_uncommitted_uses_head(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "uncommitted") == [
            "HEAD",
            "--",
            "f.py",
        ]

    def test_committed_uses_base_and_head(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "committed") == [
            "abc123",
            "HEAD",
            "--",
            "f.py",
        ]

    def test_all_uses_base_only(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "all") == [
            "abc123",
            "--",
            "f.py",
        ]
