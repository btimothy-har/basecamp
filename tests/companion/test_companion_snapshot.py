"""Tests for companion snapshot parsing and state rendering."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.companion.diff import WorkspaceStatus
from basecamp.companion.snapshot import (
    CompanionSnapshot,
    collapse_home,
    companion_snapshot_path,
    load_snapshot,
    render_workspace_lines,
)


class TestLoadSnapshot:
    """Snapshot loading behavior."""

    def test_load_valid_snapshot(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessionId": "session-123",
                    "updatedAt": "2026-06-02T12:34:56Z",
                    "goal": "Ship companion scaffold",
                    "tasks": [
                        {"label": "Implement scaffold", "status": "active", "notes": "in progress"},
                    ],
                    "progress": {"completed": 1, "total": 3},
                    "agentMode": "executor",
                    "worktree": {
                        "label": "c266-companion-dashboard",
                        "branch": "wt/c266-companion-dashboard",
                        "path": "/tmp/worktree",
                    },
                    "repoName": "basecamp",
                    "model": "gpt-5",
                    "skillsUsed": ["python-development", "planning"],
                    "effectiveCwd": "/tmp/worktree",
                }
            ),
            encoding="utf-8",
        )

        snapshot = load_snapshot(path)

        assert snapshot is not None
        assert isinstance(snapshot, CompanionSnapshot)
        assert snapshot.session_id == "session-123"
        assert snapshot.updated_at == "2026-06-02T12:34:56Z"
        assert snapshot.skills_used == ["python-development", "planning"]
        assert snapshot.agent_mode == "executor"
        assert snapshot.repo_name == "basecamp"
        assert snapshot.effective_cwd == "/tmp/worktree"

    def test_load_snapshot_missing_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        assert load_snapshot(path) is None

    def test_load_snapshot_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{invalid", encoding="utf-8")

        assert load_snapshot(path) is None

    def test_load_snapshot_missing_required_fields_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad-schema.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "updatedAt": "2026-06-02T12:34:56Z",
                }
            ),
            encoding="utf-8",
        )

        assert load_snapshot(path) is None

    def test_load_snapshot_ignores_extra_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessionId": "session-1",
                    "updatedAt": "2026-06-02T12:34:56Z",
                    "effectiveCwd": "/tmp/worktree",
                    "unknownTopLevel": "ignored",
                    "progress": {"completed": 0, "total": 0, "extra": "ignored"},
                }
            ),
            encoding="utf-8",
        )

        snapshot = load_snapshot(path)

        assert snapshot is not None
        assert snapshot.session_id == "session-1"
        assert snapshot.progress.completed == 0
        assert snapshot.progress.total == 0


class TestCompanionSnapshotPath:
    """Snapshot path helper behavior."""

    def test_sanitizes_session_id_and_uses_base_dir(self, tmp_path: Path) -> None:
        path = companion_snapshot_path("a/b:c", base_dir=tmp_path)
        assert path == tmp_path / "a_b_c.json"


class TestCollapseHome:
    """Home-path collapse helper behavior."""

    def test_collapse_path_under_home(self) -> None:
        home = Path.home()
        path = str(home / "repo" / "sub")
        assert collapse_home(path) == "~/repo/sub"

    def test_collapse_path_outside_home(self, tmp_path: Path) -> None:
        path = str(tmp_path / "repo")
        assert collapse_home(path) == path

    def test_collapse_exact_home(self) -> None:
        assert collapse_home(str(Path.home())) == "~"


class TestRenderWorkspaceLines:
    """Workspace panel line rendering behavior."""

    def test_render_waiting(self) -> None:
        lines = render_workspace_lines(None, None)
        assert lines == ["Waiting for session…"]

    def test_render_workspace_and_session(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessionId": "1111-2222-3333-abcdef",
                    "updatedAt": "2026-06-02T12:34:56Z",
                    "repoName": "basecamp",
                    "worktree": {"label": "wt-x", "branch": "wt/x", "path": "/tmp/wt"},
                    "effectiveCwd": "/tmp/wt/sub",
                }
            ),
            encoding="utf-8",
        )
        snapshot = load_snapshot(path)
        assert snapshot is not None
        status = WorkspaceStatus(
            branch="wt/x",
            base_branch="main",
            ahead=3,
            changed_files=5,
            staged=1,
            modified=2,
            untracked=1,
        )

        rendered_text = "\n".join(render_workspace_lines(snapshot, status))

        assert "basecamp" in rendered_text
        assert "wt-x" in rendered_text
        assert "main" in rendered_text
        assert "+3" in rendered_text
        assert "5 changed" in rendered_text
        assert "1 staged" in rendered_text
        assert "/tmp/wt/sub" in rendered_text
        # Session id moved to the footer; agent state is not in the workspace panel.
        assert "Session" not in rendered_text
        assert "Tasks" not in rendered_text

    def test_render_status_without_snapshot(self) -> None:
        status = WorkspaceStatus(
            branch="feature",
            base_branch="main",
            ahead=0,
            changed_files=0,
            staged=0,
            modified=0,
            untracked=0,
        )
        rendered_text = "\n".join(render_workspace_lines(None, status))
        assert "feature" in rendered_text
        assert "Session:" not in rendered_text
