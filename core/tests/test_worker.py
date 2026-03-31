"""Tests for worker management module."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from core.cli.worker import worker as worker_group
from core.exceptions import (
    InvalidWorkerNameError,
    NoMultiplexerError,
    NotAWorkerError,
    ProjectNotSetError,
    SessionIdNotSetError,
    WorkerCommunicationError,
    WorkerError,
    WorkerNotFoundError,
)
from core.worker.communication import ask_worker, send_to_worker
from core.worker.index import WorkerIndex
from core.worker.models import WorkerEntry, WorkerStatus
from core.worker.operations import close_worker, create_worker, dispatch_worker, list_workers

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def worker_env() -> dict[str, str]:
    """Minimal env vars for worker operations via tmux."""
    return {
        "TMUX": "/tmp/tmux-1000/default,12345,0",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_PROJECT": "test-project",
        "BASECAMP_REPO": "test-repo",
    }


@pytest.fixture()
def kitty_env() -> dict[str, str]:
    """Minimal env vars for worker operations via Kitty."""
    return {
        "KITTY_LISTEN_ON": "unix:/tmp/kitty-123",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_PROJECT": "test-project",
        "BASECAMP_REPO": "test-repo",
    }


@pytest.fixture()
def index(tmp_path: Path) -> WorkerIndex:
    """WorkerIndex backed by a temp directory."""
    with patch("core.worker.index.WORKERS_INDEX_DIR", tmp_path):
        yield WorkerIndex("test-project")


def _mock_subprocess_run() -> MagicMock:
    """Create a subprocess.run mock that succeeds (tmux returns pane ID)."""
    mock = MagicMock()
    mock.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")
    return mock


# -- Model tests -------------------------------------------------------------


class TestWorkerEntry:
    def test_serialization_roundtrip(self) -> None:
        entry = WorkerEntry(
            name="fix-bug",
            project="myproject",
            worker_dir="/tmp/tasks/myproject/fix-bug",
            session_id="sess-123",
            parent_session_id="session-abc",
            model="sonnet",
        )
        data = entry.model_dump(mode="json")
        restored = WorkerEntry.model_validate(data)
        assert restored.name == "fix-bug"
        assert restored.session_id == "sess-123"
        assert restored.status == WorkerStatus.STAGED
        assert restored.closed_at is None

    def test_defaults(self) -> None:
        entry = WorkerEntry(
            name="test",
            project="p",
            worker_dir="/tmp/t",
            session_id="s-1",
            parent_session_id="s",
        )
        assert entry.status == WorkerStatus.STAGED
        assert entry.model == "sonnet"
        assert entry.closed_at is None


# -- Index tests -------------------------------------------------------------


class TestWorkerIndex:
    def test_read_empty(self, index: WorkerIndex) -> None:
        assert index.read() == []

    def test_add_and_read(self, index: WorkerIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "fix-bug"
        task_dir.mkdir(parents=True)
        entry = WorkerEntry(
            name="fix-bug",
            project="test-project",
            worker_dir=str(task_dir),
            session_id="s-1",
            parent_session_id="session-1",
        )
        index.add(entry)
        entries = index.read()
        assert len(entries) == 1
        assert entries[0].name == "fix-bug"

    def test_prune_stale_entries(self, index: WorkerIndex, tmp_path: Path) -> None:
        alive_dir = tmp_path / "tasks" / "alive"
        alive_dir.mkdir(parents=True)

        alive = WorkerEntry(
            name="alive",
            project="test-project",
            worker_dir=str(alive_dir),
            session_id="s-1",
            parent_session_id="s",
        )
        dead = WorkerEntry(
            name="dead",
            project="test-project",
            worker_dir="/tmp/nonexistent-task-dir-xyz",
            session_id="s-2",
            parent_session_id="s",
        )
        index.add(alive)
        index.add(dead)

        entries = index.read()
        assert len(entries) == 1
        assert entries[0].name == "alive"

    def test_update_entry(self, index: WorkerIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "t"
        task_dir.mkdir(parents=True)
        entry = WorkerEntry(
            name="t",
            project="test-project",
            worker_dir=str(task_dir),
            session_id="s-1",
            parent_session_id="s",
        )
        index.add(entry)

        updated = index.update("t", status=WorkerStatus.DISPATCHED)
        assert updated is not None
        assert updated.status == WorkerStatus.DISPATCHED

        # Verify persisted
        reread = index.get("t")
        assert reread is not None
        assert reread.status == WorkerStatus.DISPATCHED

    def test_update_nonexistent_returns_none(self, index: WorkerIndex) -> None:
        assert index.update("nope", status=WorkerStatus.DISPATCHED) is None

    def test_remove_entry(self, index: WorkerIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "r"
        task_dir.mkdir(parents=True)
        entry = WorkerEntry(
            name="r",
            project="test-project",
            worker_dir=str(task_dir),
            session_id="s-1",
            parent_session_id="s",
        )
        index.add(entry)
        assert index.remove("r") is True
        assert index.get("r") is None

    def test_remove_nonexistent_returns_false(self, index: WorkerIndex) -> None:
        assert index.remove("nope") is False

    def test_get_entry(self, index: WorkerIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "g"
        task_dir.mkdir(parents=True)
        entry = WorkerEntry(
            name="g",
            project="test-project",
            worker_dir=str(task_dir),
            session_id="s-1",
            parent_session_id="s",
        )
        index.add(entry)
        assert index.get("g") is not None
        assert index.get("missing") is None

    def test_corrupt_index_raises(self, index: WorkerIndex) -> None:
        index._path.parent.mkdir(parents=True, exist_ok=True)
        index._path.write_text("NOT VALID JSON{{{")

        with pytest.raises(ValueError):
            index.read()


# -- Operations tests --------------------------------------------------------


class TestCreateWorker:
    def test_creates_task_dir_and_files(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            entry = create_worker(name="fix-bug", prompt="Fix the bug", model="sonnet")

        assert entry.name.endswith("-fix-bug")
        assert entry.name.startswith("worker-")
        assert entry.session_id  # pre-assigned UUID
        assert entry.status == WorkerStatus.STAGED

        task_dir = Path(entry.worker_dir)
        assert task_dir.is_dir()
        assert (task_dir / "prompt.md").read_text() == "Fix the bug"
        assert (task_dir / "launch.sh").exists()

    def test_launcher_includes_session_id(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="t", prompt="X")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--session-id" in script
        assert entry.session_id in script

    def test_launcher_includes_model(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.operations.resolve_model", side_effect=lambda m: m),
        ):
            entry = create_worker(name="t", model="opus")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--model opus" in script

    def test_launcher_resolves_extended_context(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.operations.resolve_model", return_value="opus[1m]"),
        ):
            entry = create_worker(name="ext", model="opus")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--model 'opus[1m]'" in script
        assert entry.model == "opus[1m]"

    def test_launcher_with_system_prompt(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("You are helpful")

        env = {**worker_env, "BASECAMP_SYSTEM_PROMPT": str(prompt_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="t")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--system-prompt" in script

    def test_launcher_with_settings_file(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"env": {}}')

        env = {**worker_env, "BASECAMP_SETTINGS_FILE": str(settings_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="t")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--settings" in script
        assert "--setting-sources" in script

    def test_launcher_skips_missing_settings_file(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        env = {**worker_env, "BASECAMP_SETTINGS_FILE": "/tmp/nonexistent-settings.json"}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="t")

        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--settings" not in script

    def test_bare_worker_no_prompt(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="bare")

        task_dir = Path(entry.worker_dir)
        assert not (task_dir / "prompt.md").exists()
        script = (task_dir / "launch.sh").read_text()
        assert '-- "$(cat' not in script

    def test_auto_generates_name(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker()

        assert entry.name.startswith("worker-")
        assert len(entry.name) == len("worker-") + 6

    def test_dispatch_flag_spawns_pane(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            create_worker(name="dispatched", prompt="Go", dispatch=True)

        mock_run.assert_called()

    def test_dispatch_flag_sets_status(self, worker_env: dict, tmp_path: Path) -> None:
        """create_task with dispatch=True returns entry with DISPATCHED status."""
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            entry = create_worker(name="dispatched", prompt="Go", dispatch=True)

        assert entry.status == WorkerStatus.DISPATCHED


class TestCreateWorkerValidation:
    def test_raises_no_project(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProjectNotSetError):
                create_worker(name="t")

    def test_raises_no_session_id(self) -> None:
        env = {"BASECAMP_PROJECT": "p"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(SessionIdNotSetError):
                create_worker(name="t")

    @pytest.mark.parametrize("bad_project", ["../escape", "/absolute", "has spaces"])
    def test_raises_unsafe_project(self, bad_project: str) -> None:
        env = {"BASECAMP_PROJECT": bad_project, "CLAUDE_SESSION_ID": "s"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(WorkerError, match="unsafe characters"):
                create_worker(name="t")

    @pytest.mark.parametrize(
        "bad_name",
        ["../escape", "/absolute", "has/slash", ".dotstart", "has spaces", "semi;colon"],
    )
    def test_raises_invalid_name(self, bad_name: str, worker_env: dict, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", tmp_path),
        ):
            with pytest.raises(InvalidWorkerNameError):
                create_worker(name=bad_name)


class TestDispatchWorker:
    def test_dispatches_staged_task(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            staged = create_worker(name="staged", prompt="Do work")
            entry, resumed = dispatch_worker(name=staged.name)

        assert resumed is False
        mock_run.assert_called()

    def test_resumes_already_dispatched_task(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            staged = create_worker(name="resumable", prompt="Do work")

            # Mark as dispatched (simulates a previous dispatch)
            index = WorkerIndex(worker_env["BASECAMP_PROJECT"])
            index.update(staged.name, status=WorkerStatus.DISPATCHED)

            # Second dispatch should resume
            entry, resumed = dispatch_worker(name=staged.name)

        assert resumed is True
        assert entry.session_id == staged.session_id

        # Launcher should contain --resume
        script = (Path(entry.worker_dir) / "launch.sh").read_text()
        assert "--resume" in script
        assert staged.session_id in script

    def test_resume_launcher_omits_system_prompt_and_task_prompt(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("System prompt")

        env = {**worker_env, "BASECAMP_SYSTEM_PROMPT": str(prompt_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            staged = create_worker(name="resume-clean", prompt="Original task")

            index = WorkerIndex(worker_env["BASECAMP_PROJECT"])
            index.update(staged.name, status=WorkerStatus.DISPATCHED)

            dispatch_worker(name=staged.name)

        script = (Path(staged.worker_dir) / "launch.sh").read_text()
        assert "--resume" in script
        assert "--system-prompt" not in script
        assert '-- "$(cat' not in script

    def test_raises_task_not_found(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(WorkerNotFoundError):
                dispatch_worker(name="nonexistent")

    def test_raises_no_multiplexer(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        env = {k: v for k, v in worker_env.items() if k != "TMUX"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            staged = create_worker(name="no-mux", prompt="X")
            with pytest.raises(NoMultiplexerError):
                dispatch_worker(name=staged.name)


class TestDispatchPaneManagement:
    def test_tmux_env_vars_passed(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            create_worker(name="t", prompt="Go", dispatch=True)

        split_call = mock_run.call_args_list[0]
        cmd = split_call[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "BASECAMP_WORKER_DIR=" in cmd_str
        assert "BASECAMP_WORKER_NAME=" in cmd_str
        assert "BASECAMP_PROJECT=test-project" in cmd_str
        assert "BASECAMP_REPO=test-repo" in cmd_str

    def test_tmux_sets_pane_title(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            entry = create_worker(name="titled", prompt="Go", dispatch=True)

        title_call = mock_run.call_args_list[1]
        cmd = title_call[0][0]
        assert "select-pane" in cmd
        assert entry.name in cmd

    def test_kitty_uses_socket(self, kitty_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", kitty_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            create_worker(name="k", prompt="Go", dispatch=True)

        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["kitty", "@", "--to"]
        assert cmd[3] == "unix:/tmp/kitty-123"

    def test_kitty_preferred_over_tmux(self, kitty_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()
        env = {**kitty_env, "TMUX": "/tmp/tmux-501/default,12345,0"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            create_worker(name="k", prompt="Go", dispatch=True)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "kitty"

    def test_tmux_failure_raises(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = sp.CalledProcessError(1, "tmux", stderr="session not found")
            staged = create_worker(name="fail", prompt="X")
            with pytest.raises(WorkerError, match="tmux pane launch failed"):
                dispatch_worker(name=staged.name)


class TestListWorkers:
    def test_lists_current_session_tasks(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            create_worker(name="mine", prompt="X")
            entries = list_workers()

        assert len(entries) == 1
        assert entries[0].name.endswith("-mine")

    def test_filters_by_session(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            create_worker(name="mine", prompt="X")

        # Switch session
        other_env = {**worker_env, "CLAUDE_SESSION_ID": "other-session"}
        with (
            patch.dict("os.environ", other_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            create_worker(name="theirs", prompt="Y")
            entries = list_workers()

        assert len(entries) == 1
        assert entries[0].name.endswith("-theirs")

    def test_show_all_returns_all_sessions(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            create_worker(name="first", prompt="X")

        other_env = {**worker_env, "CLAUDE_SESSION_ID": "other-session"}
        with (
            patch.dict("os.environ", other_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            create_worker(name="second", prompt="Y")
            entries = list_workers(show_all=True)

        assert len(entries) == 2


class TestCloseWorker:
    def test_closes_dispatched_task(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="closeable", prompt="X")

            env = {**worker_env, "BASECAMP_WORKER_NAME": entry.name}
            with patch.dict("os.environ", env, clear=True):
                close_worker()

            index = WorkerIndex(worker_env["BASECAMP_PROJECT"])
            updated = index.get(entry.name)

        assert updated is not None
        assert updated.status == WorkerStatus.CLOSED
        assert updated.closed_at is not None

    def test_missing_task_name_is_noop(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {k: v for k, v in worker_env.items() if k != "BASECAMP_WORKER_NAME"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            close_worker()  # should not raise

    def test_missing_project_raises(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s", "BASECAMP_WORKER_NAME": "t"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProjectNotSetError):
                close_worker()

    def test_nonexistent_task_is_noop(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {**worker_env, "BASECAMP_WORKER_NAME": "nonexistent-task"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            close_worker()  # should not raise


# -- CLI tests ---------------------------------------------------------------


class TestWorkerCLI:
    """Test the Click command layer: arg parsing, stdin, error→exit-code."""

    def test_create_reads_stdin(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(worker_group, ["create", "-n", "from-stdin"], input="Fix the bug\n")

        assert result.exit_code == 0
        # Verify prompt was written from stdin
        task_dirs = list((tasks_base / "test-project").iterdir())
        assert len(task_dirs) == 1
        assert (task_dirs[0] / "prompt.md").read_text() == "Fix the bug"

    def test_create_error_exits_nonzero(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s"}  # missing BASECAMP_PROJECT
        with patch.dict("os.environ", env, clear=True):
            result = CliRunner().invoke(worker_group, ["create", "-n", "fail"])

        assert result.exit_code == 1

    def test_close_marks_task_closed(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="close-cli", prompt="X")

            env = {**worker_env, "BASECAMP_WORKER_NAME": entry.name}
            with patch.dict("os.environ", env, clear=True):
                result = CliRunner().invoke(worker_group, ["close"])

            index = WorkerIndex(worker_env["BASECAMP_PROJECT"])
            updated = index.get(entry.name)

        assert result.exit_code == 0
        assert updated is not None
        assert updated.status == WorkerStatus.CLOSED

    def test_list_empty(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(worker_group, ["list"])

        assert result.exit_code == 0

    def test_list_error_exits_nonzero(self) -> None:
        env: dict[str, str] = {}  # missing BASECAMP_PROJECT
        with patch.dict("os.environ", env, clear=True):
            result = CliRunner().invoke(worker_group, ["list"])

        assert result.exit_code == 1

    def test_dispatch_error_exits_nonzero(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(worker_group, ["dispatch", "-n", "nonexistent"])

        assert result.exit_code == 1

    def test_ask_cli(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="cli-target", prompt="Work")

            mock_run = MagicMock()
            mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="response text", stderr="")
            with patch("core.worker.communication.subprocess.run", mock_run):
                result = CliRunner().invoke(worker_group, ["ask", "-n", entry.name, "what's up?"])

        assert result.exit_code == 0
        assert "response text" in result.output

    def test_ask_error_exits_nonzero(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(worker_group, ["ask", "-n", "nonexistent", "hello"])

        assert result.exit_code == 1

    def test_send_cli(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        inbox_base = tmp_path / "inbox"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.communication.INBOX_BASE", inbox_base),
        ):
            entry = create_worker(name="cli-target", prompt="Work")
            result = CliRunner().invoke(worker_group, ["send", "-n", entry.name, "heads up"])

        assert result.exit_code == 0
        assert "Sent" in result.output
        assert "normal" in result.output

    def test_send_immediate_cli(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        inbox_base = tmp_path / "inbox"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.communication.INBOX_BASE", inbox_base),
        ):
            entry = create_worker(name="cli-target", prompt="Work")
            result = CliRunner().invoke(worker_group, ["send", "-n", entry.name, "--immediate", "urgent"])

        assert result.exit_code == 0
        assert "immediate" in result.output

    def test_send_error_exits_nonzero(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(worker_group, ["send", "-n", "nonexistent", "hello"])

        assert result.exit_code == 1


# -- Ask worker tests --------------------------------------------------------


class TestAskWorker:
    """Tests for ask_worker (fork-based synchronous query)."""

    def test_ask_uses_fork_session(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="target", prompt="Do work")

            mock_run = MagicMock()
            mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="I'm 50% done", stderr="")
            with patch("core.worker.communication.subprocess.run", mock_run):
                result = ask_worker(name=entry.name, message="what's your status?")

        assert result == "I'm 50% done"
        cmd = mock_run.call_args[0][0]
        assert "--fork-session" in cmd
        assert "--no-session-persistence" in cmd
        assert entry.session_id in cmd

    def test_ask_parent(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="worker", prompt="Do work")

            worker_env = {**worker_env, "BASECAMP_WORKER_NAME": entry.name}
            mock_run = MagicMock()
            mock_run.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="Use approach B", stderr="")
            with (
                patch.dict("os.environ", worker_env, clear=True),
                patch("core.worker.communication.subprocess.run", mock_run),
            ):
                result = ask_worker(name="parent", message="which approach?")

        assert result == "Use approach B"
        cmd = mock_run.call_args[0][0]
        assert worker_env["CLAUDE_SESSION_ID"] in cmd

    def test_ask_parent_requires_task_name(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {k: v for k, v in worker_env.items() if k != "BASECAMP_WORKER_NAME"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(NotAWorkerError):
                ask_worker(name="parent", message="hello")

    def test_ask_nonexistent_task_raises(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(WorkerNotFoundError):
                ask_worker(name="nonexistent-task", message="hello")

    def test_ask_subprocess_failure_raises(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            entry = create_worker(name="target", prompt="Do work")

            mock_run = MagicMock()
            mock_run.return_value = sp.CompletedProcess(args=[], returncode=1, stdout="", stderr="session not found")
            with patch("core.worker.communication.subprocess.run", mock_run):
                with pytest.raises(WorkerCommunicationError, match="Communication failed"):
                    ask_worker(name=entry.name, message="hello")


# -- Send to worker tests ----------------------------------------------------


class TestSendToWorker:
    """Tests for send_to_worker (inbox file delivery)."""

    def test_send_writes_msg_file(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        inbox_base = tmp_path / "inbox"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.communication.INBOX_BASE", inbox_base),
        ):
            entry = create_worker(name="target", prompt="Do work")
            msg_path = send_to_worker(name=entry.name, message="status update")

        assert msg_path.exists()
        assert msg_path.suffix == ".msg"
        assert msg_path.read_text() == "status update"
        assert msg_path.parent == inbox_base / entry.session_id

    def test_send_immediate_writes_immediate_file(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        inbox_base = tmp_path / "inbox"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.communication.INBOX_BASE", inbox_base),
        ):
            entry = create_worker(name="target", prompt="Do work")
            msg_path = send_to_worker(name=entry.name, message="urgent!", immediate=True)

        assert msg_path.exists()
        assert msg_path.suffix == ".immediate"
        assert msg_path.read_text() == "urgent!"

    def test_send_to_parent(self, worker_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        inbox_base = tmp_path / "inbox"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.operations.WORKERS_BASE", tasks_base),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
            patch("core.worker.communication.INBOX_BASE", inbox_base),
        ):
            entry = create_worker(name="worker", prompt="Do work")

            worker_env = {**worker_env, "BASECAMP_WORKER_NAME": entry.name}
            with patch.dict("os.environ", worker_env, clear=True):
                msg_path = send_to_worker(name="parent", message="done!")

        assert msg_path.exists()
        assert msg_path.parent == inbox_base / worker_env["CLAUDE_SESSION_ID"]

    def test_send_parent_requires_task_name(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {k: v for k, v in worker_env.items() if k != "BASECAMP_WORKER_NAME"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(NotAWorkerError):
                send_to_worker(name="parent", message="hello")

    def test_send_nonexistent_task_raises(self, worker_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", worker_env, clear=True),
            patch("core.worker.index.WORKERS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(WorkerNotFoundError):
                send_to_worker(name="nonexistent-task", message="hello")
