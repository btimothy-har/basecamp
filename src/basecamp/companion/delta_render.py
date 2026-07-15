"""Render file diffs via the external `delta` viewer, captured as Rich text.

This is an optional, higher-fidelity renderer: when the `delta` binary is
available it produces side-by-side, word-level syntax-highlighted diffs that we
capture as ANSI and parse back into a Rich ``Text`` for display in the TUI.
When `delta` is absent (or produces nothing) the caller falls back to the
built-in ``difflib``-based renderer in :mod:`basecamp.companion.diff`.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from rich.text import Text

from basecamp.companion.diff import MAX_DIFF_BYTES, DiffMode, FileStatus

# delta emits ANSI background fills as spaces on a non-tty unless forced; a fixed
# width plus line-fill=ansi is required for faithful side-by-side capture.
_DELTA_ARGS = (
    "--paging",
    "never",
    "--side-by-side",
    "--line-fill-method",
    "ansi",
)
MIN_DELTA_WIDTH = 40


@lru_cache(maxsize=1)
def delta_path() -> str | None:
    """Return the path to the `delta` binary, or None when not installed."""

    return shutil.which("delta")


def _git_diff_refs(base_commit: str, file: FileStatus, mode: DiffMode) -> list[str]:
    """Build the `git diff` ref/path arguments matching the given scope.

    Mirrors the ref selection in :func:`basecamp.companion.diff.file_diff_lines`
    so the delta and fallback renderers show the identical change range.
    """

    path = file.path
    if mode == "uncommitted":
        return ["HEAD", "--", path]
    if mode == "committed":
        return [base_commit, "HEAD", "--", path]
    return [base_commit, "--", path]


def render_file_diff(
    *,
    cwd: Path,
    base_commit: str,
    file: FileStatus,
    mode: DiffMode,
    width: int,
) -> Text | None:
    """Render one file's diff through `delta`, returned as Rich ``Text``.

    Returns ``None`` when delta is unavailable, the diff is empty, or the render
    fails — signalling the caller to use the built-in renderer instead.
    """

    delta = delta_path()
    if delta is None:
        return None

    refs = _git_diff_refs(base_commit, file, mode)
    try:
        git = subprocess.run(  # noqa: S603
            ["git", "-C", str(cwd), "--no-pager", "diff", "--color=always", *refs],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if git.returncode != 0 or not git.stdout.strip():
        return None
    if len(git.stdout.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        return None

    try:
        proc = subprocess.run(  # noqa: S603
            [delta, *_DELTA_ARGS, "--width", str(max(width, MIN_DELTA_WIDTH))],
            input=git.stdout,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if proc.returncode != 0 or not proc.stdout:
        return None

    return Text.from_ansi(proc.stdout.rstrip("\n"))
