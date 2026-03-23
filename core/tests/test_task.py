"""Tests for task management module."""

from __future__ import annotations

import subprocess as sp
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from core.cli.task import task as task_group
from core.exceptions import (
    InvalidTaskNameError,
    NoMultiplexerError,
    ProjectNotSetError,
    SessionIdNotSetError,
    TaskError,
    TaskNotFoundError,
)
from core.task.index import TaskIndex
from core.task.models import TaskEntry
from core.task.operations import create_task, dispatch_task, list_tasks, register_task

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def task_env() -> dict[str, str]:
    """Minimal env vars for task operations via tmux."""
    return {
        "TMUX": "/tmp/tmux-1000/default,12345,0",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_PROJECT": "test-project",
        "BASECAMP_REPO": "test-repo",
    }


@pytest.fixture()
def kitty_env() -> dict[str, str]:
    """Minimal env vars for task operations via Kitty."""
    return {
        "KITTY_LISTEN_ON": "unix:/tmp/kitty-123",
        "CLAUDE_SESSION_ID": "test-session-123",
        "BASECAMP_PROJECT": "test-project",
        "BASECAMP_REPO": "test-repo",
    }


@pytest.fixture()
def index(tmp_path: Path) -> TaskIndex:
    """TaskIndex backed by a temp directory."""
    with patch("core.task.index.TASKS_INDEX_DIR", tmp_path):
        yield TaskIndex("test-project")


def _mock_subprocess_run() -> MagicMock:
    """Create a subprocess.run mock that succeeds (tmux returns pane ID)."""
    mock = MagicMock()
    mock.return_value = sp.CompletedProcess(args=[], returncode=0, stdout="%42\n", stderr="")
    return mock


# -- Model tests -------------------------------------------------------------


class TestTaskEntry:
    def test_serialization_roundtrip(self) -> None:
        entry = TaskEntry(
            name="fix-bug",
            project="myproject",
            task_dir="/tmp/tasks/myproject/fix-bug",
            parent_session_id="session-abc",
            model="sonnet",
        )
        data = entry.model_dump(mode="json")
        restored = TaskEntry.model_validate(data)
        assert restored.name == "fix-bug"
        assert restored.worker_session_id is None

    def test_defaults(self) -> None:
        entry = TaskEntry(
            name="test",
            project="p",
            task_dir="/tmp/t",
            parent_session_id="s",
        )
        assert entry.worker_session_id is None
        assert entry.model == "sonnet"


# -- Index tests -------------------------------------------------------------


class TestTaskIndex:
    def test_read_empty(self, index: TaskIndex) -> None:
        assert index.read() == []

    def test_add_and_read(self, index: TaskIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "fix-bug"
        task_dir.mkdir(parents=True)
        entry = TaskEntry(
            name="fix-bug",
            project="test-project",
            task_dir=str(task_dir),
            parent_session_id="session-1",
        )
        index.add(entry)
        entries = index.read()
        assert len(entries) == 1
        assert entries[0].name == "fix-bug"

    def test_prune_stale_entries(self, index: TaskIndex, tmp_path: Path) -> None:
        alive_dir = tmp_path / "tasks" / "alive"
        alive_dir.mkdir(parents=True)

        alive = TaskEntry(
            name="alive",
            project="test-project",
            task_dir=str(alive_dir),
            parent_session_id="s",
        )
        dead = TaskEntry(
            name="dead",
            project="test-project",
            task_dir="/tmp/nonexistent-task-dir-xyz",
            parent_session_id="s",
        )
        index.add(alive)
        index.add(dead)

        entries = index.read()
        assert len(entries) == 1
        assert entries[0].name == "alive"

    def test_update_entry(self, index: TaskIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "t"
        task_dir.mkdir(parents=True)
        entry = TaskEntry(
            name="t",
            project="test-project",
            task_dir=str(task_dir),
            parent_session_id="s",
        )
        index.add(entry)

        updated = index.update("t", worker_session_id="w-123")
        assert updated is not None
        assert updated.worker_session_id == "w-123"

        # Verify persisted
        reread = index.get("t")
        assert reread is not None
        assert reread.worker_session_id == "w-123"

    def test_update_nonexistent_returns_none(self, index: TaskIndex) -> None:
        assert index.update("nope", worker_session_id="w-1") is None

    def test_remove_entry(self, index: TaskIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "r"
        task_dir.mkdir(parents=True)
        entry = TaskEntry(
            name="r",
            project="test-project",
            task_dir=str(task_dir),
            parent_session_id="s",
        )
        index.add(entry)
        assert index.remove("r") is True
        assert index.get("r") is None

    def test_remove_nonexistent_returns_false(self, index: TaskIndex) -> None:
        assert index.remove("nope") is False

    def test_get_entry(self, index: TaskIndex, tmp_path: Path) -> None:
        task_dir = tmp_path / "tasks" / "g"
        task_dir.mkdir(parents=True)
        entry = TaskEntry(
            name="g",
            project="test-project",
            task_dir=str(task_dir),
            parent_session_id="s",
        )
        index.add(entry)
        assert index.get("g") is not None
        assert index.get("missing") is None

    def test_corrupt_index_raises(self, index: TaskIndex) -> None:
        index._path.parent.mkdir(parents=True, exist_ok=True)
        index._path.write_text("NOT VALID JSON{{{")

        with pytest.raises(ValueError):
            index.read()


# -- Operations tests --------------------------------------------------------


class TestCreateTask:
    def test_creates_task_dir_and_files(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
        ):
            entry = create_task(name="fix-bug", prompt="Fix the bug", model="sonnet")

        assert entry.name.endswith("-fix-bug")
        assert entry.name.startswith("worker-")

        task_dir = Path(entry.task_dir)
        assert task_dir.is_dir()
        assert (task_dir / "prompt.md").read_text() == "Fix the bug"
        assert (task_dir / "launch.sh").exists()

    def test_launcher_includes_model(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="t", model="opus")

        script = (Path(entry.task_dir) / "launch.sh").read_text()
        assert "--model opus" in script

    def test_launcher_with_system_prompt(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("You are helpful")

        env = {**task_env, "BASECAMP_SYSTEM_PROMPT": str(prompt_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="t")

        script = (Path(entry.task_dir) / "launch.sh").read_text()
        assert "--system-prompt" in script

    def test_launcher_with_settings_file(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"env": {}}')

        env = {**task_env, "BASECAMP_SETTINGS_FILE": str(settings_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="t")

        script = (Path(entry.task_dir) / "launch.sh").read_text()
        assert "--settings" in script
        assert "--setting-sources" in script

    def test_launcher_skips_missing_settings_file(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        env = {**task_env, "BASECAMP_SETTINGS_FILE": "/tmp/nonexistent-settings.json"}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="t")

        script = (Path(entry.task_dir) / "launch.sh").read_text()
        assert "--settings" not in script

    def test_bare_worker_no_prompt(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="bare")

        task_dir = Path(entry.task_dir)
        assert not (task_dir / "prompt.md").exists()
        script = (task_dir / "launch.sh").read_text()
        assert '-- "$(cat' not in script

    def test_auto_generates_name(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task()

        assert entry.name.startswith("worker-")
        assert len(entry.name) == len("worker-") + 6

    def test_dispatch_flag_spawns_pane(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            create_task(name="dispatched", prompt="Go", dispatch=True)

        mock_run.assert_called()


class TestCreateTaskValidation:
    def test_raises_no_project(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProjectNotSetError):
                create_task(name="t")

    def test_raises_no_session_id(self) -> None:
        env = {"BASECAMP_PROJECT": "p"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(SessionIdNotSetError):
                create_task(name="t")

    @pytest.mark.parametrize("bad_project", ["../escape", "/absolute", "has spaces"])
    def test_raises_unsafe_project(self, bad_project: str) -> None:
        env = {"BASECAMP_PROJECT": bad_project, "CLAUDE_SESSION_ID": "s"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(TaskError, match="unsafe characters"):
                create_task(name="t")

    @pytest.mark.parametrize(
        "bad_name",
        ["../escape", "/absolute", "has/slash", ".dotstart", "has spaces", "semi;colon"],
    )
    def test_raises_invalid_name(self, bad_name: str, task_env: dict, tmp_path: Path) -> None:
        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", tmp_path),
        ):
            with pytest.raises(InvalidTaskNameError):
                create_task(name=bad_name)


class TestDispatchTask:
    def test_dispatches_staged_task(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            staged = create_task(name="staged", prompt="Do work")
            entry, resumed = dispatch_task(name=staged.name)

        assert resumed is False
        mock_run.assert_called()

    def test_resumes_already_dispatched_task(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            staged = create_task(name="resumable", prompt="Do work")

            # Simulate first dispatch — register a worker session_id
            index = TaskIndex(task_env["BASECAMP_PROJECT"])
            index.update(staged.name, worker_session_id="worker-sess-1")

            # Second dispatch should resume
            entry, resumed = dispatch_task(name=staged.name)

        assert resumed is True
        assert entry.worker_session_id == "worker-sess-1"

        # Launcher should contain --resume
        script = (Path(entry.task_dir) / "launch.sh").read_text()
        assert "--resume" in script
        assert "worker-sess-1" in script

    def test_resume_launcher_omits_system_prompt_and_task_prompt(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("System prompt")

        env = {**task_env, "BASECAMP_SYSTEM_PROMPT": str(prompt_file)}
        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            staged = create_task(name="resume-clean", prompt="Original task")

            index = TaskIndex(task_env["BASECAMP_PROJECT"])
            index.update(staged.name, worker_session_id="sess-abc")

            dispatch_task(name=staged.name)

        script = (Path(staged.task_dir) / "launch.sh").read_text()
        assert "--resume" in script
        assert "--system-prompt" not in script
        assert '-- "$(cat' not in script

    def test_raises_task_not_found(self, task_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            with pytest.raises(TaskNotFoundError):
                dispatch_task(name="nonexistent")

    def test_raises_no_multiplexer(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        env = {k: v for k, v in task_env.items() if k != "TMUX"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            staged = create_task(name="no-mux", prompt="X")
            with pytest.raises(NoMultiplexerError):
                dispatch_task(name=staged.name)


class TestDispatchPaneManagement:
    def test_tmux_env_vars_passed(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            create_task(name="t", prompt="Go", dispatch=True)

        split_call = mock_run.call_args_list[0]
        cmd = split_call[0][0]
        cmd_str = " ".join(str(c) for c in cmd)
        assert "BASECAMP_TASK_DIR=" in cmd_str
        assert "BASECAMP_TASK_NAME=" in cmd_str
        assert "BASECAMP_PROJECT=test-project" in cmd_str
        assert "BASECAMP_REPO=test-repo" in cmd_str

    def test_tmux_sets_pane_title(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"
        mock_run = _mock_subprocess_run()

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            entry = create_task(name="titled", prompt="Go", dispatch=True)

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
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            create_task(name="k", prompt="Go", dispatch=True)

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
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run", mock_run),
            patch("core.task.operations.time.sleep"),
        ):
            create_task(name="k", prompt="Go", dispatch=True)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "kitty"

    def test_tmux_failure_raises(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
            patch("core.terminal.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = sp.CalledProcessError(1, "tmux", stderr="session not found")
            staged = create_task(name="fail", prompt="X")
            with pytest.raises(TaskError, match="tmux pane launch failed"):
                dispatch_task(name=staged.name)


class TestListTasks:
    def test_lists_current_session_tasks(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="mine", prompt="X")
            entries = list_tasks()

        assert len(entries) == 1
        assert entries[0].name.endswith("-mine")

    def test_filters_by_session(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="mine", prompt="X")

        # Switch session
        other_env = {**task_env, "CLAUDE_SESSION_ID": "other-session"}
        with (
            patch.dict("os.environ", other_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="theirs", prompt="Y")
            entries = list_tasks()

        assert len(entries) == 1
        assert entries[0].name.endswith("-theirs")

    def test_show_all_returns_all_sessions(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="first", prompt="X")

        other_env = {**task_env, "CLAUDE_SESSION_ID": "other-session"}
        with (
            patch.dict("os.environ", other_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="second", prompt="Y")
            entries = list_tasks(show_all=True)

        assert len(entries) == 2

    def test_enriches_worker_session_id(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="enriched", prompt="X")

            # Simulate worker registering session_id via the index
            index = TaskIndex(task_env["BASECAMP_PROJECT"])
            index.update(entry.name, worker_session_id="worker-abc-123")

            entries = list_tasks()

        assert entries[0].worker_session_id == "worker-abc-123"

    def test_unregistered_worker_has_no_session_id(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            create_task(name="stale", prompt="X")
            entries = list_tasks()

        assert entries[0].worker_session_id is None


class TestRegisterTask:
    def test_registers_session_id(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="reg", prompt="X")

            env = {**task_env, "BASECAMP_TASK_NAME": entry.name}
            with patch.dict("os.environ", env, clear=True):
                register_task(session_id="worker-sess-42")

            index = TaskIndex(task_env["BASECAMP_PROJECT"])
            updated = index.get(entry.name)

        assert updated is not None
        assert updated.worker_session_id == "worker-sess-42"

    def test_missing_task_name_is_noop(self, task_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {k: v for k, v in task_env.items() if k != "BASECAMP_TASK_NAME"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            register_task(session_id="worker-sess-1")

    def test_missing_project_raises(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s", "BASECAMP_TASK_NAME": "t"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ProjectNotSetError):
                register_task(session_id="worker-sess-1")

    def test_nonexistent_task_is_noop(self, task_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        env = {**task_env, "BASECAMP_TASK_NAME": "nonexistent-task"}

        with (
            patch.dict("os.environ", env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            register_task(session_id="worker-sess-1")  # should not raise


# -- CLI tests ---------------------------------------------------------------


class TestTaskCLI:
    """Test the Click command layer: arg parsing, stdin, error→exit-code."""

    def test_create_reads_stdin(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(task_group, ["create", "-n", "from-stdin"], input="Fix the bug\n")

        assert result.exit_code == 0
        # Verify prompt was written from stdin
        task_dirs = list((tasks_base / "test-project").iterdir())
        assert len(task_dirs) == 1
        assert (task_dirs[0] / "prompt.md").read_text() == "Fix the bug"

    def test_create_error_exits_nonzero(self) -> None:
        env = {"CLAUDE_SESSION_ID": "s"}  # missing BASECAMP_PROJECT
        with patch.dict("os.environ", env, clear=True):
            result = CliRunner().invoke(task_group, ["create", "-n", "fail"])

        assert result.exit_code == 1

    def test_register_passes_session_id(self, task_env: dict, tmp_path: Path) -> None:
        tasks_base = tmp_path / "tasks"
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.operations.TASKS_BASE", tasks_base),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            entry = create_task(name="reg-cli", prompt="X")

            env = {**task_env, "BASECAMP_TASK_NAME": entry.name}
            with patch.dict("os.environ", env, clear=True):
                result = CliRunner().invoke(task_group, ["register", "worker-sess-99"])

            index = TaskIndex(task_env["BASECAMP_PROJECT"])
            updated = index.get(entry.name)

        assert result.exit_code == 0
        assert updated is not None
        assert updated.worker_session_id == "worker-sess-99"

    def test_list_empty(self, task_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(task_group, ["list"])

        assert result.exit_code == 0

    def test_list_error_exits_nonzero(self) -> None:
        env: dict[str, str] = {}  # missing BASECAMP_PROJECT
        with patch.dict("os.environ", env, clear=True):
            result = CliRunner().invoke(task_group, ["list"])

        assert result.exit_code == 1

    def test_dispatch_error_exits_nonzero(self, task_env: dict, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"

        with (
            patch.dict("os.environ", task_env, clear=True),
            patch("core.task.index.TASKS_INDEX_DIR", index_dir),
        ):
            result = CliRunner().invoke(task_group, ["dispatch", "-n", "nonexistent"])

        assert result.exit_code == 1
