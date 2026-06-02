"""Tests for companion snapshot parsing and state rendering."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.companion.snapshot import (
    CompanionSnapshot,
    companion_snapshot_path,
    load_snapshot,
    render_state_lines,
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


class TestRenderStateLines:
    """State panel line rendering behavior."""

    def test_render_waiting(self) -> None:
        lines = render_state_lines(None)
        assert lines == ["Waiting for session…"]

    def test_render_snapshot_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "snapshot.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sessionId": "session-1",
                    "updatedAt": "2026-06-02T12:34:56Z",
                    "goal": "Build panel",
                    "tasks": [
                        {"label": "Done task", "status": "completed"},
                        {"label": "Active task", "status": "active"},
                        {"label": "Pending task", "status": "pending"},
                        {"label": "Deleted task", "status": "deleted"},
                    ],
                    "progress": {"completed": 1, "total": 3},
                    "skillsUsed": ["python-development", "sql"],
                    "effectiveCwd": "/tmp/worktree",
                }
            ),
            encoding="utf-8",
        )
        snapshot = load_snapshot(path)
        assert snapshot is not None

        lines = render_state_lines(snapshot)
        rendered_text = "\n".join(lines)

        assert "Build panel" in rendered_text
        assert "1/3" in rendered_text
        assert "✓ Done task" in rendered_text
        assert "→ Active task" in rendered_text
        assert "☐ Pending task" in rendered_text
        assert "Deleted task" not in rendered_text
        assert "📖 python-development, sql" in rendered_text
