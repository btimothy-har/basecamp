"""Immutable Git snapshots for transferring canonical-checkout work into a scratch."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.omp.workspace_environment import clear_git_location_environment

_COMMAND_TIMEOUT_SECONDS = 60
_WORKSPACE_ID = re.compile(r"[0-9a-f]{32}")
_DIFF_FLAGS = (
    "--binary",
    "--full-index",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
    "--no-color",
)


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Recovery objects and semantic worktree state captured from one Git checkout."""

    head: str
    index_tree: str
    content_tree: str
    index_signature: str
    index_path: Path
    snapshot_ref: str
    has_uncommitted_work: bool


@dataclass(frozen=True)
class _WorktreeState:
    head: str
    head_tree: str
    index_tree: str
    content_tree: str
    index_signature: str
    visible_intent_diff: bytes
    invisible_intent_diff: bytes
    index_path: Path

    @property
    def has_uncommitted_work(self) -> bool:
        return (
            self.index_tree != self.head_tree
            or self.content_tree != self.head_tree
            or self.visible_intent_diff != self.invisible_intent_diff
        )


def capture_snapshot(
    source_root: Path,
    snapshot_dir: Path,
    workspace_id: str,
) -> WorkspaceSnapshot:
    """Capture source index and content without mutating its index, branch, or files."""
    source = source_root.resolve()
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        message = f"Invalid workspace id for scratch snapshot: {workspace_id}"
        raise LauncherError(message)
    _prepare_snapshot_directory(snapshot_dir)
    final_index = snapshot_dir / "index"
    snapshot_ref = f"refs/basecamp/omp/snapshots/{workspace_id}"

    state: _WorktreeState | None = None
    for attempt in range(2):
        candidate = snapshot_dir / f"index.capture-{attempt}"
        try:
            state = _capture_state(source, candidate, preflight=True)
            verified = _capture_state(source, snapshot_dir / f"index.verify-{attempt}", preflight=True)
        finally:
            _remove_private_files(snapshot_dir, prefix="index.verify-")
        if _same_state(state, verified):
            os.replace(candidate, final_index)
            os.chmod(final_index, 0o600)
            break
        candidate.unlink(missing_ok=True)
        state = None
    if state is None:
        message = "source changed while creating the scratch snapshot; retry the launch."
        raise LauncherError(message)

    index_commit = _commit_tree(
        source,
        state.index_tree,
        parents=(state.head,),
        message=f"Basecamp scratch index {workspace_id}\n",
    )
    content_commit = _commit_tree(
        source,
        state.content_tree,
        parents=(state.head, index_commit),
        message=f"Basecamp scratch content {workspace_id}\n",
    )
    _run_git(source, "update-ref", snapshot_ref, content_commit, "")
    return WorkspaceSnapshot(
        head=state.head,
        index_tree=state.index_tree,
        content_tree=state.content_tree,
        index_signature=state.index_signature,
        index_path=final_index,
        snapshot_ref=snapshot_ref,
        has_uncommitted_work=state.has_uncommitted_work,
    )


def restore_snapshot(snapshot: WorkspaceSnapshot, target_root: Path) -> None:
    """Restore captured content and staging into an exclusively owned scratch."""
    target = target_root.resolve()
    current_head = _run_git(target, "rev-parse", "--verify", "HEAD").decode().strip()
    if current_head != snapshot.head:
        message = f"Scratch HEAD changed before snapshot restore: {target}"
        raise LauncherError(message)
    if not snapshot.index_path.is_file():
        message = f"Scratch snapshot index is missing: {snapshot.index_path}"
        raise LauncherError(message)

    _run_git(target, "read-tree", "--reset", "-u", snapshot.content_tree)
    target_index = _git_path(target, "index")
    target_index.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="index.basecamp-", dir=target_index.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream, snapshot.index_path.open("rb") as source:
            shutil.copyfileobj(source, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target_index)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise


def matches_snapshot(snapshot: WorkspaceSnapshot, target_root: Path) -> bool:
    """Return whether a checkout still has the complete captured semantic state."""
    state = _capture_comparison_state(target_root)
    return state is not None and _matches_snapshot_state(snapshot, state)


def matches_disposable_state(snapshot: WorkspaceSnapshot, target_root: Path) -> bool:
    """Accept the captured state or a plain reset to the same pinned HEAD."""
    target = target_root.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="bomp-compare-") as directory:
            private_dir = Path(directory)
            state = _capture_state(target, private_dir / "index", preflight=True)
            if _matches_snapshot_state(snapshot, state):
                return True
            if state.head != snapshot.head or state.has_uncommitted_work:
                return False
            clean_index = private_dir / "clean-index"
            environment = _index_environment(clean_index)
            _run_git(target, "read-tree", state.head, environ=environment)
            visible = _cached_diff(target, state.head, environment, visible=True)
            invisible = _cached_diff(target, state.head, environment, visible=False)
            clean_signature = _index_signature(target, environment, visible, invisible)
            return state.index_signature == clean_signature
    except (LauncherError, OSError, subprocess.SubprocessError):
        return False


def _capture_comparison_state(target_root: Path) -> _WorktreeState | None:
    target = target_root.resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="bomp-compare-") as directory:
            return _capture_state(target, Path(directory) / "index", preflight=True)
    except (LauncherError, OSError, subprocess.SubprocessError):
        return None


def _matches_snapshot_state(snapshot: WorkspaceSnapshot, state: _WorktreeState) -> bool:
    return (
        state.head == snapshot.head
        and state.index_tree == snapshot.index_tree
        and state.content_tree == snapshot.content_tree
        and state.index_signature == snapshot.index_signature
    )


def delete_snapshot_ref(snapshot: WorkspaceSnapshot, source_root: Path) -> str | None:
    """Release private recovery objects without disrupting launch cleanup."""
    try:
        _run_git(source_root.resolve(), "update-ref", "-d", snapshot.snapshot_ref)
    except LauncherError as exc:
        return str(exc)
    return None


def _capture_state(root: Path, index_path: Path, *, preflight: bool) -> _WorktreeState:
    head = _require_head(root)
    head_tree = _run_git(root, "rev-parse", f"{head}^{{tree}}").decode().strip()
    approved_gitlinks = _preflight(root, head) if preflight else {}
    _copy_standalone_index(root, index_path)
    index_environment = _index_environment(index_path)
    index_tree = _run_git(root, "write-tree", environ=index_environment).decode().strip()
    visible_diff = _cached_diff(root, head, index_environment, visible=True)
    invisible_diff = _cached_diff(root, head, index_environment, visible=False)
    intent_to_add_paths = _intent_to_add_paths(root, head, index_environment)
    signature = _index_signature(root, index_environment, visible_diff, invisible_diff)

    content_index = index_path.with_name(f"{index_path.name}.content")
    try:
        content_environment = _index_environment(content_index)
        _run_git(root, "read-tree", index_tree, environ=content_environment)
        _run_git(root, "add", "-A", environ=content_environment)
        materialized_intent_paths = b"\0".join(
            raw_path for raw_path in intent_to_add_paths if os.path.lexists(root / os.fsdecode(raw_path))
        )
        if materialized_intent_paths:
            _run_git(
                root,
                "add",
                "-f",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
                environ=content_environment,
                input_bytes=materialized_intent_paths + b"\0",
            )
        content_tree = (
            _run_git(
                root,
                "write-tree",
                environ=content_environment,
            )
            .decode()
            .strip()
        )
    finally:
        content_index.unlink(missing_ok=True)
        content_index.with_name(f"{content_index.name}.lock").unlink(missing_ok=True)
    _validate_content_gitlinks(root, content_tree, approved_gitlinks)
    return _WorktreeState(
        head=head,
        head_tree=head_tree,
        index_tree=index_tree,
        content_tree=content_tree,
        index_signature=signature,
        visible_intent_diff=visible_diff,
        invisible_intent_diff=invisible_diff,
        index_path=index_path,
    )


def _copy_standalone_index(root: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_index = _git_path(root, "index")
    destination.unlink(missing_ok=True)
    if source_index.is_file():
        shutil.copyfile(source_index, destination)
        os.chmod(destination, 0o600)
    else:
        _run_git(root, "read-tree", "--empty", environ=_index_environment(destination))
    environment = _index_environment(destination)
    _run_git(root, "update-index", "--no-split-index", environ=environment)
    _run_git(root, "update-index", "--no-fsmonitor", environ=environment)
    _run_git(root, "update-index", "--no-untracked-cache", environ=environment)
    os.chmod(destination, 0o600)


def _preflight(root: Path, head: str) -> dict[str, str]:
    sparse = _run_git(root, "config", "--bool", "core.sparseCheckout", check=False).decode().strip()
    if sparse == "true":
        _unsupported("sparse checkout is enabled")

    stage_entries = _stage_entries(_run_git(root, "ls-files", "--stage", "-z"))
    if any(stage != 0 for _mode, _oid, stage, _path in stage_entries):
        _unsupported("the source index has unresolved entries")
    tags = _run_git(root, "ls-files", "-t", "-z").split(b"\0")
    if any(entry.startswith(b"S ") for entry in tags if entry):
        _unsupported("the source index contains skip-worktree entries")

    head_gitlinks = _tree_gitlinks(root, head)
    index_gitlinks = {path: oid for mode, oid, stage, path in stage_entries if mode == "160000" and stage == 0}
    if index_gitlinks != head_gitlinks:
        _unsupported("submodule gitlinks differ between HEAD and the index")
    for relative, expected_head in head_gitlinks.items():
        _validate_submodule(root, relative, expected_head)
    return head_gitlinks


def _validate_submodule(root: Path, relative: str, expected_head: str) -> None:
    path = root / relative
    if not path.is_dir():
        return
    top = _run_git(path, "rev-parse", "--show-toplevel", check=False).decode().strip()
    if not top or Path(top).resolve() != path.resolve():
        return
    actual_head = _run_git(path, "rev-parse", "--verify", "HEAD").decode().strip()
    status = _run_git(
        path,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        environ={"GIT_OPTIONAL_LOCKS": "0"},
    )
    if actual_head != expected_head or status:
        _unsupported(f"submodule {relative} is changed")


def _validate_content_gitlinks(root: Path, tree: str, approved: Mapping[str, str]) -> None:
    if _tree_gitlinks(root, tree) != dict(approved):
        _unsupported("the copied content contains a new or changed embedded repository")


def _tree_gitlinks(root: Path, treeish: str) -> dict[str, str]:
    entries = _run_git(root, "ls-tree", "-r", "-z", treeish).split(b"\0")
    gitlinks: dict[str, str] = {}
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, _kind, oid = metadata.decode().split(" ", 2)
        if mode == "160000":
            gitlinks[os.fsdecode(raw_path)] = oid
    return gitlinks


def _stage_entries(payload: bytes) -> list[tuple[str, str, int, str]]:
    entries: list[tuple[str, str, int, str]] = []
    for entry in payload.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split(" ", 2)
        entries.append((mode, oid, int(stage), os.fsdecode(raw_path)))
    return entries


def _cached_diff(root: Path, head: str, environment: Mapping[str, str], *, visible: bool) -> bytes:
    intent_flag = "--ita-visible-in-index" if visible else "--ita-invisible-in-index"
    return _run_git(
        root,
        "diff",
        "--cached",
        *_DIFF_FLAGS,
        intent_flag,
        head,
        "--",
        environ=environment,
    )


def _intent_to_add_paths(root: Path, head: str, environment: Mapping[str, str]) -> frozenset[bytes]:
    def names(*, visible: bool) -> frozenset[bytes]:
        intent_flag = "--ita-visible-in-index" if visible else "--ita-invisible-in-index"
        payload = _run_git(
            root,
            "diff",
            "--cached",
            "--name-only",
            "-z",
            intent_flag,
            head,
            "--",
            environ=environment,
        )
        return frozenset(path for path in payload.split(b"\0") if path)

    return names(visible=True) - names(visible=False)


def _index_signature(
    root: Path,
    environment: Mapping[str, str],
    visible_diff: bytes,
    invisible_diff: bytes,
) -> str:
    listing = _run_git(root, "ls-files", "-v", "-z", environ=environment)
    digest = hashlib.sha256()
    for payload in (listing, visible_diff, invisible_diff):
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _same_state(left: _WorktreeState, right: _WorktreeState) -> bool:
    return (
        left.head == right.head
        and left.index_tree == right.index_tree
        and left.content_tree == right.content_tree
        and left.index_signature == right.index_signature
    )


def _commit_tree(root: Path, tree: str, *, parents: Sequence[str], message: str) -> str:
    arguments = ["-c", "commit.gpgsign=false", "commit-tree", tree]
    for parent in parents:
        arguments.extend(("-p", parent))
    identity = {
        "GIT_AUTHOR_NAME": "Basecamp",
        "GIT_AUTHOR_EMAIL": "basecamp@localhost",
        "GIT_COMMITTER_NAME": "Basecamp",
        "GIT_COMMITTER_EMAIL": "basecamp@localhost",
    }
    return _run_git(root, *arguments, environ=identity, input_bytes=message.encode()).decode().strip()


def _require_head(root: Path) -> str:
    result = _run_git(root, "rev-parse", "--verify", "HEAD", check=False).decode().strip()
    if not result:
        _unsupported("the source checkout has no commit")
    return result


def _git_path(root: Path, name: str) -> Path:
    value = _run_git(root, "rev-parse", "--path-format=absolute", "--git-path", name).decode().strip()
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _index_environment(index_path: Path) -> dict[str, str]:
    return {"GIT_INDEX_FILE": str(index_path.resolve()), "GIT_OPTIONAL_LOCKS": "0"}


def _run_git(
    cwd: Path,
    *args: str,
    environ: Mapping[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> bytes:
    environment = clear_git_location_environment(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    if environ is not None:
        environment.update(environ)
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            env=environment,
            input=input_bytes,
            check=False,
            capture_output=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Could not capture Git scratch snapshot at {cwd}: {exc}"
        raise LauncherError(message) from exc
    if check and result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or f"exit status {result.returncode}"
        message = f"Could not capture Git scratch snapshot at {cwd}: {detail}"
        raise LauncherError(message)
    return result.stdout if result.returncode == 0 else b""


def _prepare_snapshot_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(path, 0o700)
    except OSError as exc:
        message = f"Could not create scratch snapshot directory {path}: {exc}"
        raise LauncherError(message) from exc


def _remove_private_files(path: Path, *, prefix: str) -> None:
    for candidate in path.glob(f"{prefix}*"):
        candidate.unlink(missing_ok=True)


def _unsupported(condition: str) -> None:
    message = (
        f"Cannot copy this checkout because {condition}. Use bomp --direct to inspect this checkout without copying it."
    )
    raise LauncherError(message)
