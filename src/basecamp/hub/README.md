# hub (Python portion)

`basecamp.hub` — the host-global daemon every session and agent connects to. A FastAPI app is served over a Unix domain socket (`app.py`, run via `server.py`), with a SQLite store (`store/`, at `~/.pi/basecamp/swarm/daemon.db` — the runtime dir keeps its legacy `swarm/` segment), agent runtime (`swarm/`), and WebSocket frame contract (`frames/`) kept in lockstep with the TypeScript client and wire protocol in `pi/core/hub/` — see `pi/core/hub/protocol/PROTOCOL.md`.

Run as the daemon behind the `basecamp` CLI (entry point in `src/basecamp/cli.py`). Tests live in `tests/hub/`.
