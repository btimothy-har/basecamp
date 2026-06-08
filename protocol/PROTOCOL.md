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

## Manual smoke check

```bash
basecamp daemon --uds /tmp/basecamp-daemon.sock
```

Then, in another shell:

```bash
curl --unix-socket /tmp/basecamp-daemon.sock http://localhost/health
```
