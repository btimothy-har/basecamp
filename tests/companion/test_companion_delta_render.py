"""Tests for the delta-backed diff renderer."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rich.text import Text

from basecamp.companion import delta_render
from basecamp.companion.delta_render import delta_path, render_file_diff
from basecamp.companion.diff import COMPACT_CONTEXT_LINES, MAX_DIFF_LINES, DiffDensity, DiffLayout, FileStatus


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
            scope="uncommitted",
            density="full",
            layout="split",
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
            scope="uncommitted",
            density="full",
            layout="split",
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
            scope="uncommitted",
            density="full",
            layout="split",
            width=120,
        )
        assert isinstance(result, Text)
        # Both sides of the change should appear in the captured render.
        assert "return" in result.plain
        # delta emitted styling that Rich parsed into spans.
        assert result.spans

    @pytest.mark.parametrize(
        ("density", "layout", "context_lines"),
        [
            ("full", "stacked", MAX_DIFF_LINES),
            ("full", "split", MAX_DIFF_LINES),
            ("compact", "stacked", COMPACT_CONTEXT_LINES),
            ("compact", "split", COMPACT_CONTEXT_LINES),
        ],
    )
    def test_density_and_layout_control_commands(
        self,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        density: DiffDensity,
        layout: DiffLayout,
        context_lines: int,
    ) -> None:
        monkeypatch.setattr(delta_render, "delta_path", lambda: "/usr/bin/delta")
        captured: dict[str, list[str]] = {}

        def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            if cmd[0] == "git":
                captured["git"] = cmd
                return subprocess.CompletedProcess(cmd, 0, stdout="patch", stderr="")
            captured["delta"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="\x1b[31mx\x1b[0m", stderr="")

        monkeypatch.setattr(delta_render.subprocess, "run", fake_run)
        result = render_file_diff(
            cwd=repo,
            base_commit="HEAD",
            file=FileStatus(path="sample.py", status="modified"),
            scope="uncommitted",
            density=density,
            layout=layout,
            width=90,
        )

        assert isinstance(result, Text)
        assert f"--unified={context_lines}" in captured["git"]
        assert "--no-gitconfig" in captured["delta"]
        assert "--line-numbers" in captured["delta"]
        assert ("--side-by-side" in captured["delta"]) is (layout == "split")
        assert ("--line-fill-method" in captured["delta"]) is (layout == "split")
        assert captured["delta"][-2:] == ["--width", "90"]


class TestGitDiffRefs:
    """The git ref selection must mirror file_diff_lines scopes."""

    def test_uncommitted_uses_head(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "uncommitted") == [
            "-M",
            "HEAD",
            "--",
            "f.py",
        ]

    def test_committed_uses_base_and_head(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "committed") == [
            "-M",
            "abc123",
            "HEAD",
            "--",
            "f.py",
        ]

    def test_all_uses_base_only(self) -> None:
        assert delta_render._git_diff_refs("abc123", FileStatus(path="f.py", status="modified"), "all") == [
            "-M",
            "abc123",
            "--",
            "f.py",
        ]

    def test_renamed_includes_old_path(self) -> None:
        refs = delta_render._git_diff_refs(
            "abc123",
            FileStatus(path="new.py", status="renamed", old_path="old.py"),
            "all",
        )
        assert refs == ["-M", "abc123", "--", "old.py", "new.py"]


class TestRenamedFileRender:
    """A renamed+edited file must render its real change, not a whole-file add."""

    def test_renamed_edited_file_is_not_all_added(self, tmp_path: Path) -> None:
        _clear_cache()
        if delta_path() is None:
            pytest.skip("delta binary not installed")

        _run(tmp_path, "init", "-q")
        _run(tmp_path, "config", "user.email", "t@t.test")
        _run(tmp_path, "config", "user.name", "t")
        # A realistically-sized file: git's rename detection ignores tiny files,
        # so a 3-line fixture would render identically with or without the fix.
        # Distinct non-prefix markers top and bottom, filler in between.
        lines = ["UNIQUETOPMARKER"] + [f"filler_{i}" for i in range(2, 40)] + ["UNIQUEBOTTOMMARKER"]
        (tmp_path / "old.txt").write_text("\n".join(lines) + "\n")
        _run(tmp_path, "add", "-A")
        _run(tmp_path, "commit", "-q", "-m", "init")
        # Rename, then edit exactly one line in the middle of the working tree.
        _run(tmp_path, "mv", "old.txt", "new.txt")
        lines[20] = "filler_21_THEEDIT"
        (tmp_path / "new.txt").write_text("\n".join(lines) + "\n")

        result = render_file_diff(
            cwd=tmp_path,
            base_commit="HEAD",
            file=FileStatus(path="new.txt", status="renamed", old_path="old.txt"),
            scope="uncommitted",
            density="compact",
            layout="split",
            width=140,
        )
        assert isinstance(result, Text)
        # The one real edit is shown...
        assert "THEEDIT" in result.plain
        # ...but the distant unchanged top/bottom lines must NOT appear: a
        # rename-paired diff renders only the changed hunk + nearby context.
        # The pre-fix refs (single path, no -M) rendered the whole file as
        # added, so both markers were present — asserting their absence fails
        # if the rename fix is reverted (verified against the buggy refs).
        assert "UNIQUETOPMARKER" not in result.plain
        assert "UNIQUEBOTTOMMARKER" not in result.plain
