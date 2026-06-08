"""Deterministic fake daemon-spawned agent for dispatch round-trip tests."""

from __future__ import annotations

import json
import os

from websockets.sync.client import unix_connect


def main() -> int:
    uds_path = os.environ["BASECAMP_DAEMON_UDS"]
    run_id = os.environ["BASECAMP_RUN_ID"]
    agent_id = os.environ["BASECAMP_AGENT_ID"]
    parent = os.environ.get("BASECAMP_PARENT_SESSION")
    depth = int(os.environ.get("BASECAMP_AGENT_DEPTH", "0"))

    with unix_connect(uds_path, uri="ws://localhost/ws") as websocket:
        websocket.send(
            json.dumps(
                {
                    "type": "register",
                    "v": 1,
                    "role": "agent",
                    "node_id": agent_id,
                    "parent_id": parent,
                    "sibling_group": None,
                    "depth": depth,
                    "session_name": agent_id,
                    "cwd": os.getcwd(),
                }
            )
        )
        websocket.recv()

        websocket.send(
            json.dumps(
                {
                    "type": "telemetry",
                    "v": 1,
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "kind": "turn_end",
                    "payload": {"turnIndex": 1},
                }
            )
        )
        websocket.send(
            json.dumps(
                {
                    "type": "result_report",
                    "v": 1,
                    "run_id": run_id,
                    "agent_id": agent_id,
                    "status": "ok",
                    "result": "fake-agent-result",
                    "error": None,
                    "usage": None,
                }
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
