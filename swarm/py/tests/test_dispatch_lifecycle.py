"""Agent process lifecycle tests: argv/env build, terminate, spawn, reap."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest
from basecamp.swarm.frames import DispatchSpec
from basecamp.swarm.process import (
    _process_group_is_runner,
    build_child_env,
    build_runner_argv,
    reap_agent_process,
    spawn_agent_process,
    terminate_process_group,
    terminate_process_group_if_runner,
)
from basecamp.swarm.registry import Registry
from basecamp.swarm.store import Store
from dispatch_helpers import _FailingStore, _FakeProcess, _StoreFailureError

pytestmark = pytest.mark.usefixtures("_isolate_run_result_home")


def test_build_runner_argv_injects_fork_before_task() -> None:
    spec = DispatchSpec(
        argv=["pi", "--mode", "json", "-p"],
        env={},
        cwd="/tmp/project",
        resume_path=None,
        task="answer this question",
    )

    argv = build_runner_argv(
        result_path=Path("/tmp/result.json"),
        spec=spec,
        fork_source_path="/tmp/source.jsonl",
    )

    assert argv == [
        sys.executable,
        "-m",
        "basecamp.swarm.runner",
        "--result-path",
        "/tmp/result.json",
        "--",
        "pi",
        "--mode",
        "json",
        "-p",
        "--fork",
        "/tmp/source.jsonl",
        "answer this question",
    ]


def test_build_child_env_strips_inherited_handle_and_uses_daemon_supplied() -> None:
    env = build_child_env(
        spec_env={"BASECAMP_AGENT_HANDLE": "spoofed-handle", "KEEP": "1"},
        daemon_socket_path="/tmp/daemon.sock",
        run_id="run-1",
        report_token="token",
        agent_id="agent-1",
        dispatcher_node_id="root",
        child_depth=1,
        agent_handle="canonical-handle",
    )

    assert env["BASECAMP_AGENT_HANDLE"] == "canonical-handle"
    assert env["KEEP"] == "1"
    assert env["BASECAMP_AGENT_ID"] == "agent-1"


def test_build_child_env_drops_inherited_handle_when_none_supplied() -> None:
    env = build_child_env(
        spec_env={"BASECAMP_AGENT_HANDLE": "spoofed-handle"},
        daemon_socket_path="/tmp/daemon.sock",
        run_id="run-1",
        report_token="token",
        agent_id="agent-1",
        dispatcher_node_id="root",
        child_depth=1,
        agent_handle=None,
    )

    assert "BASECAMP_AGENT_HANDLE" not in env


def test_build_runner_argv_omits_fork_when_unset() -> None:
    spec = DispatchSpec(
        argv=["pi", "--mode", "json", "-p"],
        env={},
        cwd="/tmp/project",
        resume_path=None,
        task="answer this question",
    )

    argv = build_runner_argv(
        result_path=Path("/tmp/result.json"),
        spec=spec,
        fork_source_path=None,
    )

    assert "--fork" not in argv
    assert argv[-1] == "answer this question"


@pytest.mark.parametrize("pgid", [0, 1, -1])
def test_terminate_process_group_ignores_unsafe_pgids(
    pgid: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(target_pgid: int, sig: int) -> None:
        calls.append((target_pgid, sig))

    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)

    terminate_process_group(pgid)

    assert calls == []


def test_terminate_process_group_skips_sigkill_when_group_dies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)

    terminate_process_group(123, escalation_s=0.02, poll_s=0.005)

    assert calls == [(123, signal.SIGTERM), (123, 0)]


def test_terminate_process_group_escalates_when_group_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    times = iter([0.0, 0.0, 0.03])

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)
    monkeypatch.setattr("basecamp.swarm.process.time.monotonic", lambda: next(times))
    monkeypatch.setattr("basecamp.swarm.process.time.sleep", lambda _seconds: None)

    terminate_process_group(123, escalation_s=0.02, poll_s=0.005)

    assert calls == [(123, signal.SIGTERM), (123, 0), (123, signal.SIGKILL)]


def test_terminate_process_group_returns_when_initial_sigterm_finds_no_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)

    terminate_process_group(123, escalation_s=0.02, poll_s=0.005)

    assert calls == [(123, signal.SIGTERM)]


def test_terminate_process_group_tolerates_sigkill_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []
    times = iter([0.0, 0.0, 0.03])

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))
        if sig == 0 or sig == signal.SIGKILL:
            raise PermissionError

    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)
    monkeypatch.setattr("basecamp.swarm.process.time.monotonic", lambda: next(times))
    monkeypatch.setattr("basecamp.swarm.process.time.sleep", lambda _seconds: None)

    terminate_process_group(123, escalation_s=0.02, poll_s=0.005)

    assert calls == [(123, signal.SIGTERM), (123, 0), (123, signal.SIGKILL)]


def test_terminate_process_group_if_runner_terminates_verified_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    monkeypatch.setattr("basecamp.swarm.process._process_group_is_runner", lambda _pgid: True)
    monkeypatch.setattr("basecamp.swarm.process._process_group_alive", lambda _pgid: False)
    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)
    monkeypatch.setattr("basecamp.swarm.process.time.monotonic", lambda: 0.0)

    terminate_process_group_if_runner(123, escalation_s=0.02)

    assert calls == [(123, signal.SIGTERM)]


def test_terminate_process_group_if_runner_skips_unverified_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        calls.append((pgid, sig))

    monkeypatch.setattr("basecamp.swarm.process._process_group_is_runner", lambda _pgid: False)
    monkeypatch.setattr("basecamp.swarm.process.os.killpg", fake_killpg)

    terminate_process_group_if_runner(123, escalation_s=0)

    assert calls == []


def test_process_group_is_runner_matches_module_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunResult:
        stdout = "/usr/bin/python -m basecamp.swarm.runner --result-path /tmp/result.json"

    def fake_run(args: list[str], **kwargs: object) -> FakeRunResult:
        assert args == ["ps", "-p", "123", "-o", "args="]
        assert kwargs == {"capture_output": True, "text": True, "check": False}
        return FakeRunResult()

    monkeypatch.setattr("basecamp.swarm.process.subprocess.run", fake_run)

    assert _process_group_is_runner(123) is True


def test_process_group_is_runner_rejects_module_name_without_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunResult:
        stdout = "/usr/bin/python basecamp.swarm.runner --result-path /tmp/result.json"

    def fake_run(args: list[str], **kwargs: object) -> FakeRunResult:
        assert args == ["ps", "-p", "123", "-o", "args="]
        assert kwargs == {"capture_output": True, "text": True, "check": False}
        return FakeRunResult()

    monkeypatch.setattr("basecamp.swarm.process.subprocess.run", fake_run)

    assert _process_group_is_runner(123) is False


@pytest.mark.asyncio
async def test_spawn_agent_process_starts_new_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()
    captured_kwargs: dict[str, object] = {}

    async def fake_create_subprocess_exec(*_argv: str, **kwargs: object) -> _FakeProcess:
        captured_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(
        "basecamp.swarm.process.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    spec = DispatchSpec(
        argv=["pi", "--mode", "json", "-p"],
        env={"HOME": str(tmp_path)},
        cwd=str(tmp_path),
        resume_path=None,
        task="answer this question",
    )

    spawned = await spawn_agent_process(
        run_id="run-1",
        spec=spec,
        agent_id="agent-1",
        report_token="token-1",
        daemon_socket_path="/tmp/daemon.sock",
        dispatcher_node_id="root",
        child_depth=1,
    )

    assert spawned is process
    assert captured_kwargs["start_new_session"] is True


@pytest.mark.asyncio
async def test_reap_agent_process_removes_registry_process_when_store_update_fails() -> None:
    run_id = "run-failing-store"
    registry = Registry()
    process = _FakeProcess()
    registry.set_process(run_id, process)

    async def on_finalize(_run_id: str) -> None:
        raise AssertionError

    with pytest.raises(_StoreFailureError):
        await reap_agent_process(
            run_id=run_id,
            process=process,
            registry=registry,
            store=_FailingStore(),
            on_finalize=on_finalize,
        )

    assert registry.pop_process(run_id) is None


@pytest.mark.asyncio
async def test_reap_agent_process_does_not_overwrite_reported_result(tmp_path: Path) -> None:
    run_id = "run-already-reported"
    agent_id = "agent-already-reported"
    registry = Registry()
    process = _FakeProcess()
    store = Store(db_path=tmp_path / "daemon.db")
    finalized: list[str] = []

    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=None,
        parent_id=None,
        sibling_group=None,
        depth=1,
        role="agent",
        session_name=agent_id,
        cwd=str(tmp_path),
    )
    store.create_run(
        run_id=run_id,
        agent_id=agent_id,
        dispatcher_id="session-node",
        spec={},
    )
    store.set_run_result_if_unset(
        run_id=run_id,
        status="completed",
        result="runner-final-result",
        error=None,
    )
    registry.set_process(run_id, process)

    async def on_finalize(finalized_run_id: str) -> None:
        finalized.append(finalized_run_id)

    await reap_agent_process(
        run_id=run_id,
        process=process,
        registry=registry,
        store=store,
        on_finalize=on_finalize,
    )

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["result"] == "runner-final-result"
    assert run["exit_code"] == 7
    assert finalized == []
    assert registry.pop_process(run_id) is None
