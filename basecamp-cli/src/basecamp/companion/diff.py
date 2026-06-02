"""Git-backed diff helpers for the companion dashboard."""

from __future__ import annotations

import difflib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type GitRunner = Callable[[list[str]], tuple[int, str]]
type DiffMode = Literal["all", "uncommitted", "committed"]

MAX_DIFF_LINES = 2000
MAX_DIFF_BYTES = 512 * 1024
DIFF_MODES: tuple[DiffMode, ...] = ("all", "uncommitted", "committed")


@dataclass(frozen=True)
class FileStatus:
    """Git status for a single file path."""

    path: str
    status: Literal["added", "modified", "deleted", "renamed"]
    old_path: str | None = None


@dataclass(frozen=True)
class DiffLine:
    """Line-level diff entry mapped to current-file line numbers."""

    kind: Literal["context", "added", "removed", "gap"]
    text: str
    line_no: int | None


@dataclass(frozen=True)
class WorkspaceStatus:
    """Summary of the working tree relative to the base branch."""

    branch: str | None
    base_branch: str | None
    ahead: int
    changed_files: int
    staged: int
    modified: int
    untracked: int


def make_git_runner(cwd: Path) -> GitRunner:
    """Build a git runner bound to a working directory."""

    def run(args: list[str]) -> tuple[int, str]:
        proc = subprocess.run(  # noqa: S603
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout

    return run


def detect_base_branch(git: GitRunner) -> str | None:
    """Detect the most likely base branch reference."""

    code, output = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    if code == 0:
        ref = output.strip()
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix):
            branch_name = ref.removeprefix(prefix)
            if branch_name:
                return f"origin/{branch_name}"

    for candidate in ("main", "master"):
        origin_candidate = f"origin/{candidate}"
        code, _ = git(["rev-parse", "--verify", "--quiet", origin_candidate])
        if code == 0:
            return origin_candidate

        code, _ = git(["rev-parse", "--verify", "--quiet", candidate])
        if code == 0:
            return candidate

    return None


def merge_base(git: GitRunner, base_ref: str) -> str | None:
    """Resolve merge-base SHA for base branch and HEAD."""

    code, output = git(["merge-base", base_ref, "HEAD"])
    if code != 0:
        return None

    merge_base_sha = output.strip()
    if not merge_base_sha:
        return None

    return merge_base_sha


def _parse_name_status_line(line: str) -> FileStatus | None:
    """Parse one `git diff --name-status` line into a file status."""

    parts = line.split("\t")
    if not parts or not parts[0]:
        return None

    raw_status = parts[0]
    status_code = raw_status[0]

    if status_code == "A" and len(parts) >= 2:
        return FileStatus(path=parts[1], status="added")
    if status_code == "M" and len(parts) >= 2:
        return FileStatus(path=parts[1], status="modified")
    if status_code == "D" and len(parts) >= 2:
        return FileStatus(path=parts[1], status="deleted")
    if status_code == "R" and len(parts) >= 3:
        return FileStatus(path=parts[2], status="renamed", old_path=parts[1])

    return None


def list_changed_files(git: GitRunner, refs: list[str], *, include_untracked: bool) -> list[FileStatus]:
    """List changed files for `git diff --name-status -M <refs>`, optionally adding untracked."""

    entries_by_path: dict[str, FileStatus] = {}

    code, output = git(["diff", "--name-status", "-M", *refs, "--"])
    if code == 0:
        for raw_line in output.splitlines():
            entry = _parse_name_status_line(raw_line)
            if entry is not None:
                entries_by_path[entry.path] = entry

    if include_untracked:
        code, output = git(["ls-files", "--others", "--exclude-standard"])
        if code == 0:
            for path in output.splitlines():
                if path and path not in entries_by_path:
                    entries_by_path[path] = FileStatus(path=path, status="added")

    return sorted(entries_by_path.values(), key=lambda file_status: file_status.path)


def read_base_content(git: GitRunner, base_commit: str, path: str) -> str | None:
    """Read file content from the base commit tree."""

    code, output = git(["show", f"{base_commit}:{path}"])
    if code != 0:
        return None

    return output


def compute_file_diff(base_text: str | None, current_text: str | None) -> list[DiffLine]:
    """Compute line-level diff records with current-file line mapping."""

    if base_text is None and current_text is None:
        return []

    if base_text is None:
        return [
            DiffLine(kind="added", text=line, line_no=index)
            for index, line in enumerate((current_text or "").splitlines(), start=1)
        ]

    if current_text is None:
        return [DiffLine(kind="removed", text=line, line_no=None) for line in base_text.splitlines()]

    base_lines = base_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = difflib.SequenceMatcher(None, base_lines, current_lines)

    result: list[DiffLine] = []
    for opcode, base_start, base_end, current_start, current_end in matcher.get_opcodes():
        if opcode == "equal":
            result.extend(
                DiffLine(kind="context", text=text, line_no=current_start + offset + 1)
                for offset, text in enumerate(current_lines[current_start:current_end], start=0)
            )
            continue

        if opcode in {"replace", "delete"}:
            result.extend(DiffLine(kind="removed", text=text, line_no=None) for text in base_lines[base_start:base_end])

        if opcode in {"replace", "insert"}:
            result.extend(
                DiffLine(kind="added", text=text, line_no=current_start + offset + 1)
                for offset, text in enumerate(current_lines[current_start:current_end], start=0)
            )

    return result


def collapse_unchanged(lines: list[DiffLine], context: int = 3) -> list[DiffLine]:
    """Collapse long unchanged runs while preserving changed-line order."""

    if not lines:
        return []

    context = max(context, 0)
    changed_indexes = [index for index, line in enumerate(lines) if line.kind in {"added", "removed"}]
    if not changed_indexes:
        return list(lines)

    first_changed = changed_indexes[0]
    last_changed = changed_indexes[-1]

    def make_gap(hidden_count: int) -> DiffLine:
        return DiffLine(kind="gap", text=f"⋯ {hidden_count} unchanged lines", line_no=None)

    collapsed: list[DiffLine] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.kind != "context":
            collapsed.append(line)
            index += 1
            continue

        run_end = index
        while run_end < len(lines) and lines[run_end].kind == "context":
            run_end += 1

        run = lines[index:run_end]
        run_length = len(run)

        if run_end <= first_changed:
            keep = min(context, run_length)
            hidden = run_length - keep
            if hidden > 0:
                collapsed.append(make_gap(hidden))
            if keep > 0:
                collapsed.extend(run[-keep:])
        elif index > last_changed:
            keep = min(context, run_length)
            if keep > 0:
                collapsed.extend(run[:keep])
            hidden = run_length - keep
            if hidden > 0:
                collapsed.append(make_gap(hidden))
        elif run_length > (2 * context):
            keep = min(context, run_length)
            if keep > 0:
                collapsed.extend(run[:keep])
            hidden = run_length - (2 * keep)
            if hidden > 0:
                collapsed.append(make_gap(hidden))
            if keep > 0:
                collapsed.extend(run[-keep:])
        else:
            collapsed.extend(run)

        index = run_end

    return collapsed


def is_probably_binary(data: bytes) -> bool:
    """Detect likely binary file content."""

    if b"\x00" in data:
        return True

    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True

    return False


def collect_changes(git: GitRunner, mode: DiffMode = "all") -> tuple[str | None, list[FileStatus]]:
    """Collect base commit and changed file list for the given diff scope."""

    base_branch = detect_base_branch(git)
    if base_branch is None:
        return None, []

    base_commit = merge_base(git, base_branch)
    if base_commit is None:
        return None, []

    if mode == "uncommitted":
        refs, include_untracked = ["HEAD"], True
    elif mode == "committed":
        refs, include_untracked = [base_commit, "HEAD"], False
    else:
        refs, include_untracked = [base_commit], True

    changed_files = list_changed_files(git, refs, include_untracked=include_untracked)
    return base_commit, changed_files


def count_porcelain(output: str) -> tuple[int, int, int]:
    """Count (staged, modified, untracked) entries from `git status --porcelain`."""

    staged = 0
    modified = 0
    untracked = 0
    for line in output.splitlines():
        if not line:
            continue
        if line.startswith("??"):
            untracked += 1
            continue
        index_status = line[0]
        worktree_status = line[1] if len(line) > 1 else " "
        if index_status not in (" ", "?"):
            staged += 1
        if worktree_status in ("M", "D"):
            modified += 1
    return staged, modified, untracked


def git_status_summary(git: GitRunner, base_commit: str | None, changed_files: int) -> WorkspaceStatus:
    """Summarize branch, base-branch lead, and working-tree counts."""

    code, branch_out = git(["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch_out.strip() if code == 0 and branch_out.strip() else None

    base_branch = detect_base_branch(git)

    ahead = 0
    if base_commit is not None:
        code, ahead_out = git(["rev-list", "--count", f"{base_commit}..HEAD"])
        if code == 0 and ahead_out.strip().isdigit():
            ahead = int(ahead_out.strip())

    staged = modified = untracked = 0
    code, porcelain = git(["status", "--porcelain"])
    if code == 0:
        staged, modified, untracked = count_porcelain(porcelain)

    return WorkspaceStatus(
        branch=branch,
        base_branch=base_branch,
        ahead=ahead,
        changed_files=changed_files,
        staged=staged,
        modified=modified,
        untracked=untracked,
    )


def _line_count(text: str | None) -> int:
    """Return splitlines count for guard checks."""

    if text is None:
        return 0

    return len(text.splitlines())


def file_diff_lines(
    git: GitRunner,
    base_commit: str,
    file: FileStatus,
    cwd: Path,
    mode: DiffMode = "all",
) -> tuple[str, list[DiffLine]]:
    """Return placeholder message plus full-file diff lines for one file in the given scope."""

    base_ref = "HEAD" if mode == "uncommitted" else base_commit
    base_text = read_base_content(git, base_ref, file.path)
    if base_text is not None and "\x00" in base_text:
        return "Binary file — not shown", []

    if mode == "committed":
        current_text = read_base_content(git, "HEAD", file.path)
        if current_text is not None and "\x00" in current_text:
            return "Binary file — not shown", []
        if current_text is not None and len(current_text.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
            size_bytes = len(current_text.encode("utf-8", errors="ignore"))
            return f"File too large ({size_bytes} bytes) — not shown", []
    else:
        current_bytes: bytes | None = None
        if file.status != "deleted":
            try:
                current_bytes = (cwd / file.path).read_bytes()
            except OSError:
                current_bytes = None
        if current_bytes is not None:
            if is_probably_binary(current_bytes):
                return "Binary file — not shown", []
            if len(current_bytes) > MAX_DIFF_BYTES:
                return f"File too large ({len(current_bytes)} bytes) — not shown", []
        current_text = None if current_bytes is None else current_bytes.decode("utf-8")

    if base_text is not None and len(base_text.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        size_bytes = len(base_text.encode("utf-8", errors="ignore"))
        return f"File too large ({size_bytes} bytes) — not shown", []

    max_line_count = max(_line_count(base_text), _line_count(current_text))
    if max_line_count > MAX_DIFF_LINES:
        return f"File too large ({max_line_count} lines) — not shown", []

    return "", compute_file_diff(base_text=base_text, current_text=current_text)
