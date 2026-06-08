# Basecamp Daemon Protocol (Phase 1)

Protocol version: `1`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":1,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 1`, the daemon sends:
  `{"type":"error","v":1,"code":"protocol_version","message":"..."}`
  and closes the connection.

## Transport

- HTTP over Unix domain socket (UDS):
  - `GET /health` → `{"status":"ok","protocol":1}`
- WebSocket over UDS:
  - `/ws`
  - First inbound frame must be a valid `register` frame.
  - On success daemon replies with `registered`.

## Frame types

- `register` (client→daemon)
- `registered` (daemon→client)
- `error` (daemon→client)
- `dispatch` (client→daemon)
- `dispatch_ack` (daemon→client)
- `telemetry` (agent→daemon)
- `result_report` (agent→daemon)
- `wait` (client→daemon)
- `wait_result` (daemon→client)

Canonical example fixtures live in `protocol/frames/*.json`.

## UDS permissions note

`basecamp daemon` sets `umask(0o177)` before binding UDS so the socket is created with restrictive user-only permissions (effectively `0600` under standard Unix socket mode masking).

## Running the daemon (Phase 1)

Default socket path:

- `~/.pi/agent/basecamp/daemon.sock`

Start daemon manually:

```bash
basecamp daemon --uds ~/.pi/agent/basecamp/daemon.sock
```

Health check:

```bash
curl --unix-socket ~/.pi/agent/basecamp/daemon.sock http://localhost/health
# {"status":"ok","protocol":1}
```

How it normally runs:

- The extension auto-runs ensure-daemon at session start.
- `dispatch_agent` drives dispatch/spawn/result flow via daemon `/ws`.
- `wait_for_agent` waits on run completion.
- Phase-1 note: `dispatch.spec.resume_path` is accepted but ignored.

Stop daemon:

- If foreground: `Ctrl+C`.
- If background: stop the daemon process by PID (for example `pkill -f "basecamp daemon --uds"`).

Optional manual dispatch smoke:

```bash
uv run python - <<'PY'
import json, os, uuid
from websockets.sync.client import unix_connect

uds = os.path.expanduser("~/.pi/agent/basecamp/daemon.sock")
run_id = f"run-{uuid.uuid4()}"

with unix_connect(uds, uri="ws://localhost/ws") as ws:
    ws.send(json.dumps({
        "type": "register",
        "v": 1,
        "role": "session",
        "node_id": "smoke-session",
        "parent_id": None,
        "sibling_group": None,
        "depth": 0,
        "session_name": "smoke-session",
        "cwd": ".",
    }))
    print("registered:", ws.recv())

    ws.send(json.dumps({
        "type": "dispatch",
        "v": 1,
        "run_id": run_id,
        "spec": {
            "argv": ["pi", "--mode", "json", "-p"],
            "env": {},
            "cwd": ".",
            "resume_path": None,
            "task": "reply with exactly: async smoke ok",
        },
    }))
    print("dispatch_ack:", ws.recv())
PY
```
