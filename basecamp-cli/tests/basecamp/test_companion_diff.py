"""Tests for companion git/diff helpers."""

from __future__ import annotations

from pathlib import Path

from basecamp.companion.diff import (
    MAX_DIFF_LINES,
    DiffLine,
    FileStatus,
    collapse_unchanged,
    compute_file_diff,
    count_porcelain,
    detect_base_branch,
    file_diff_lines,
    git_status_summary,
    is_probably_binary,
    list_changed_files,
)


class FakeGit:
    """Fake git runner keyed by arg tuple."""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]]) -> None:
        self._responses = responses

    def __call__(self, args: list[str]) -> tuple[int, str]:
        return self._responses.get(tuple(args), (1, ""))


class TestDetectBaseBranch:
    """Base branch detection behavior."""

    def test_detects_origin_head_symbolic_ref(self) -> None:
        git = FakeGit(
            {
                ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"): (
                    0,
                    "refs/remotes/origin/main\n",
                ),
            }
        )

        assert detect_base_branch(git) == "origin/main"

    def test_falls_back_to_main_when_symbolic_ref_fails(self) -> None:
        git = FakeGit(
            {
                ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"): (1, ""),
                ("rev-parse", "--verify", "--quiet", "origin/main"): (1, ""),
                ("rev-parse", "--verify", "--quiet", "main"): (0, "main\n"),
            }
        )

        assert detect_base_branch(git) == "main"

    def test_falls_back_to_master(self) -> None:
        git = FakeGit(
            {
                ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"): (1, ""),
                ("rev-parse", "--verify", "--quiet", "origin/main"): (1, ""),
                ("rev-parse", "--verify", "--quiet", "main"): (1, ""),
                ("rev-parse", "--verify", "--quiet", "origin/master"): (0, "origin/master\n"),
            }
        )

        assert detect_base_branch(git) == "origin/master"


class TestListChangedFiles:
    """Changed-file parsing and merge behavior."""

    def test_parses_statuses_and_merges_untracked(self) -> None:
        git = FakeGit(
            {
                (
                    "diff",
                    "--name-status",
                    "-M",
                    "abc123",
                    "--",
                ): (
                    0,
                    "\n".join(
                        [
                            "A\talpha.txt",
                            "M\tbeta.py",
                            "D\tgamma.md",
                            "R100\told/name.txt\tnew/name.txt",
                        ]
                    )
                    + "\n",
                ),
                ("ls-files", "--others", "--exclude-standard"): (
                    0,
                    "zeta.txt\nalpha.txt\n",
                ),
            }
        )

        files = list_changed_files(git, "abc123")

        assert files == [
            FileStatus(path="alpha.txt", status="added"),
            FileStatus(path="beta.py", status="modified"),
            FileStatus(path="gamma.md", status="deleted"),
            FileStatus(path="new/name.txt", status="renamed", old_path="old/name.txt"),
            FileStatus(path="zeta.txt", status="added"),
        ]


class TestComputeFileDiff:
    """Pure line-diff behavior."""

    def test_added_file_marks_all_lines_added(self) -> None:
        lines = compute_file_diff(base_text=None, current_text="one\ntwo\n")

        assert lines == [
            DiffLine(kind="added", text="one", line_no=1),
            DiffLine(kind="added", text="two", line_no=2),
        ]

    def test_deleted_file_marks_all_lines_removed(self) -> None:
        lines = compute_file_diff(base_text="one\ntwo\n", current_text=None)

        assert lines == [
            DiffLine(kind="removed", text="one", line_no=None),
            DiffLine(kind="removed", text="two", line_no=None),
        ]

    def test_modification_includes_context_removed_and_added(self) -> None:
        lines = compute_file_diff(base_text="a\nb\nc\n", current_text="a\nB\nc\n")

        assert lines == [
            DiffLine(kind="context", text="a", line_no=1),
            DiffLine(kind="removed", text="b", line_no=None),
            DiffLine(kind="added", text="B", line_no=2),
            DiffLine(kind="context", text="c", line_no=3),
        ]

    def test_identical_text_is_all_context(self) -> None:
        lines = compute_file_diff(base_text="same\ntext\n", current_text="same\ntext\n")

        assert lines == [
            DiffLine(kind="context", text="same", line_no=1),
            DiffLine(kind="context", text="text", line_no=2),
        ]


class TestCollapseUnchanged:
    """Compaction behavior for unchanged runs."""

    def test_long_interior_run_collapses_with_gap(self) -> None:
        lines = [
            DiffLine(kind="added", text="changed-start", line_no=1),
            *[DiffLine(kind="context", text=f"context-{index}", line_no=index + 1) for index in range(8)],
            DiffLine(kind="removed", text="changed-end", line_no=None),
        ]

        collapsed = collapse_unchanged(lines, context=2)

        assert collapsed == [
            DiffLine(kind="added", text="changed-start", line_no=1),
            DiffLine(kind="context", text="context-0", line_no=1),
            DiffLine(kind="context", text="context-1", line_no=2),
            DiffLine(kind="gap", text="⋯ 4 unchanged lines", line_no=None),
            DiffLine(kind="context", text="context-6", line_no=7),
            DiffLine(kind="context", text="context-7", line_no=8),
            DiffLine(kind="removed", text="changed-end", line_no=None),
        ]

    def test_short_interior_run_is_not_collapsed(self) -> None:
        lines = [
            DiffLine(kind="removed", text="before", line_no=None),
            *[DiffLine(kind="context", text=f"context-{index}", line_no=index + 1) for index in range(4)],
            DiffLine(kind="added", text="after", line_no=5),
        ]

        collapsed = collapse_unchanged(lines, context=2)

        assert collapsed == lines

    def test_leading_and_trailing_runs_collapse(self) -> None:
        lines = [
            *[DiffLine(kind="context", text=f"lead-{index}", line_no=index + 1) for index in range(6)],
            DiffLine(kind="added", text="change", line_no=7),
            *[DiffLine(kind="context", text=f"tail-{index}", line_no=index + 8) for index in range(5)],
        ]

        collapsed = collapse_unchanged(lines, context=2)

        assert collapsed == [
            DiffLine(kind="gap", text="⋯ 4 unchanged lines", line_no=None),
            DiffLine(kind="context", text="lead-4", line_no=5),
            DiffLine(kind="context", text="lead-5", line_no=6),
            DiffLine(kind="added", text="change", line_no=7),
            DiffLine(kind="context", text="tail-0", line_no=8),
            DiffLine(kind="context", text="tail-1", line_no=9),
            DiffLine(kind="gap", text="⋯ 3 unchanged lines", line_no=None),
        ]

    def test_changed_lines_are_always_preserved_in_order(self) -> None:
        lines = [
            DiffLine(kind="context", text="lead", line_no=1),
            DiffLine(kind="removed", text="r1", line_no=None),
            *[DiffLine(kind="context", text=f"mid-{index}", line_no=index + 2) for index in range(10)],
            DiffLine(kind="added", text="a1", line_no=12),
            DiffLine(kind="removed", text="r2", line_no=None),
            DiffLine(kind="context", text="tail", line_no=13),
        ]

        collapsed = collapse_unchanged(lines, context=2)

        changed = [line for line in collapsed if line.kind in {"added", "removed"}]
        assert changed == [
            DiffLine(kind="removed", text="r1", line_no=None),
            DiffLine(kind="added", text="a1", line_no=12),
            DiffLine(kind="removed", text="r2", line_no=None),
        ]


class TestBinaryAndGuards:
    """Binary detection and size-guard behavior."""

    def test_is_probably_binary(self) -> None:
        assert is_probably_binary(b"a\x00b") is True
        assert is_probably_binary(b"\xff") is True
        assert is_probably_binary(b"hello") is False

    def test_file_diff_lines_reports_oversized_file(self, tmp_path: Path) -> None:
        content = "\n".join(f"line {index}" for index in range(MAX_DIFF_LINES + 1))
        file_path = tmp_path / "big.txt"
        file_path.write_text(content, encoding="utf-8")

        git = FakeGit(
            {
                ("show", "base123:big.txt"): (1, ""),
            }
        )
        status = FileStatus(path="big.txt", status="added")

        message, lines = file_diff_lines(git=git, base_commit="base123", file=status, cwd=tmp_path)

        assert message.startswith("File too large")
        assert lines == []


class TestGitStatusSummary:
    """Working-tree status summary behavior."""

    def test_count_porcelain(self) -> None:
        output = "\n".join(["M  staged.py", " M modified.py", "?? new.py", "MM both.py", " D gone.py"])
        staged, modified, untracked = count_porcelain(output)
        assert staged == 2  # staged.py, both.py
        assert modified == 3  # modified.py, both.py, gone.py
        assert untracked == 1  # new.py

    def test_git_status_summary(self) -> None:
        git = FakeGit(
            {
                ("rev-parse", "--abbrev-ref", "HEAD"): (0, "wt/feature\n"),
                ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"): (0, "refs/remotes/origin/main\n"),
                ("rev-list", "--count", "base999..HEAD"): (0, "4\n"),
                ("status", "--porcelain"): (0, "M  a.py\n M b.py\n?? c.py\n"),
            }
        )

        status = git_status_summary(git, base_commit="base999", changed_files=7)

        assert status.branch == "wt/feature"
        assert status.base_branch == "origin/main"
        assert status.ahead == 4
        assert status.changed_files == 7
        assert status.staged == 1
        assert status.modified == 1
        assert status.untracked == 1
