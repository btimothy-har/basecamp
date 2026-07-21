"""Render file diffs via the external `delta` viewer, captured as Rich text.

This is an optional, higher-fidelity renderer: when the `delta` binary is
available it produces stacked or split, word-level syntax-highlighted diffs that
we capture as ANSI and parse back into a Rich ``Text`` for display in the TUI.
When `delta` is absent (or produces nothing) the caller falls back to the
built-in ``difflib``-based renderer in :mod:`basecamp.companion.diff`.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from rich.text import Text

from basecamp.companion.diff import (
    COMPACT_CONTEXT_LINES,
    FULL_CONTEXT_LINES,
    MAX_DIFF_BYTES,
    DiffDensity,
    DiffLayout,
    DiffScope,
    FileStatus,
)

# Companion owns layout; ignoring git config prevents a global side-by-side=true
# from overriding the selected stacked layout.
_DELTA_ARGS = ("--paging", "never", "--no-gitconfig", "--line-numbers")
_DELTA_SPLIT_ARGS = ("--side-by-side", "--line-fill-method", "ansi")
MIN_DELTA_WIDTH = 40


@lru_cache(maxsize=1)
def delta_path() -> str | None:
    """Return the path to the `delta` binary, or None when not installed."""

    return shutil.which("delta")


def _git_diff_refs(base_commit: str, file: FileStatus, scope: DiffScope) -> list[str]:
    """Build the `git diff` ref/path arguments matching the given scope.

    Mirrors the ref selection in :func:`basecamp.companion.diff.file_diff_lines`
    so the delta and fallback renderers show the identical change range. Rename
    detection (`-M`) plus the old path are included when the file was renamed, so
    a renamed+edited file shows its true change rather than a whole-file add.
    """

    # Pathspec covers both endpoints of a rename so git can pair old -> new.
    paths = [file.old_path, file.path] if file.old_path else [file.path]
    pathspec = ["--", *paths]

    if scope == "uncommitted":
        return ["-M", "HEAD", *pathspec]
    if scope == "committed":
        return ["-M", base_commit, "HEAD", *pathspec]
    return ["-M", base_commit, *pathspec]


def render_file_diff(
    *,
    cwd: Path,
    base_commit: str,
    file: FileStatus,
    scope: DiffScope,
    density: DiffDensity,
    layout: DiffLayout,
    width: int,
) -> Text | None:
    """Render one file's diff through `delta`, returned as Rich ``Text``.

    Returns ``None`` when delta is unavailable, the diff is empty, or the render
    fails — signalling the caller to use the built-in renderer instead.
    """

    delta = delta_path()
    if delta is None:
        return None

    refs = _git_diff_refs(base_commit, file, scope)
    context_lines = COMPACT_CONTEXT_LINES if density == "compact" else FULL_CONTEXT_LINES
    try:
        git = subprocess.run(  # noqa: S603
            [
                "git",
                "-C",
                str(cwd),
                "--no-pager",
                "diff",
                "--color=always",
                f"--unified={context_lines}",
                *refs,
            ],
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

    delta_args = [delta, *_DELTA_ARGS]
    if layout == "split":
        delta_args.extend(_DELTA_SPLIT_ARGS)
    delta_args.extend(("--width", str(max(width, MIN_DELTA_WIDTH))))

    try:
        proc = subprocess.run(  # noqa: S603
            delta_args,
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
