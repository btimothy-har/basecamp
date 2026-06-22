"""Deterministic fake daemon-spawned agent for dispatch round-trip tests."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from pi_swarm.frames import PROTOCOL_VERSION
from pi_swarm.run_result import (
    BASECAMP_RUN_ATTEMPT,
    BASECAMP_RUN_RESULT_PATH,
    BASECAMP_RUNNER_MANAGED_RESULT,
    RunResultAttempt,
    RunResultSidecar,
    load_run_result,
    write_run_result,
)
from websockets.sync.client import unix_connect


def _fake_result_value() -> str:
    result_value = "fake-agent-result"
    env_key = os.environ.get("FAKE_DAEMON_AGENT_RESULT_ENV_KEY")
    if env_key:
        result_value = f"{result_value}:{env_key}={os.environ.get(env_key, '')}"
    return result_value


def _attempt_result_value() -> str:
    mode = os.environ.get("FAKE_DAEMON_AGENT_MODE", "ok")
    attempt = int(os.environ.get(BASECAMP_RUN_ATTEMPT, "1"))
    if mode == "empty_first_attempt" and attempt == 1:
        return ""
    return _fake_result_value()


def _write_attempt_result(*, run_id: str, agent_id: str) -> None:
    result_path = Path(os.environ[BASECAMP_RUN_RESULT_PATH])
    attempt = int(os.environ[BASECAMP_RUN_ATTEMPT])
    sidecar = load_run_result(result_path) or RunResultSidecar(
        run_id=run_id,
        agent_id=agent_id,
        attempts=[],
        final=None,
    )
    sidecar.attempts.append(
        RunResultAttempt(
            attempt=attempt,
            status="ok",
            result=_attempt_result_value(),
            error=None,
        )
    )
    write_run_result(result_path, sidecar)


def main() -> int:
    uds_path = os.environ["BASECAMP_DAEMON_UDS"]
    run_id = os.environ["BASECAMP_RUN_ID"]
    agent_id = os.environ["BASECAMP_AGENT_ID"]
    report_token = os.environ["BASECAMP_REPORT_TOKEN"]
    parent = os.environ.get("BASECAMP_PARENT_SESSION")
    depth = int(os.environ.get("BASECAMP_AGENT_DEPTH", "0"))
    node_id = os.environ.get("FAKE_DAEMON_AGENT_NODE_ID", agent_id)
    token_dump_path = os.environ.get("FAKE_DAEMON_AGENT_REPORT_TOKEN_PATH")
    if token_dump_path:
        Path(token_dump_path).write_text(report_token, encoding="utf-8")

    mode = os.environ.get("FAKE_DAEMON_AGENT_MODE", "ok")
    sleep_ms = int(os.environ.get("FAKE_DAEMON_AGENT_SLEEP_MS", "0"))
    if sleep_ms > 0:
        time.sleep(sleep_ms / 1000)

    with unix_connect(uds_path, uri="ws://localhost/ws") as websocket:
        websocket.send(
            json.dumps(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "agent",
                    "node_id": node_id,
                    "parent_id": parent,
                    "sibling_group": None,
                    "depth": depth,
                    "session_name": node_id,
                    "cwd": os.getcwd(),
                }
            )
        )
        websocket.recv()

        websocket.send(
            json.dumps(
                {
                    "type": "telemetry",
                    "v": PROTOCOL_VERSION,
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "report_token": report_token,
                    "kind": "turn_end",
                    "payload": {"turnIndex": 1},
                }
            )
        )

        if mode == "no_result_exit":
            return int(os.environ.get("FAKE_DAEMON_AGENT_EXIT_CODE", "7"))

        if os.environ.get(BASECAMP_RUNNER_MANAGED_RESULT) == "1":
            _write_attempt_result(run_id=run_id, agent_id=agent_id)
            return 0

        websocket.send(
            json.dumps(
                {
                    "type": "result_report",
                    "v": PROTOCOL_VERSION,
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "report_token": report_token,
                    "status": "ok",
                    "result": _fake_result_value(),
                    "error": None,
                    "usage": None,
                }
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
