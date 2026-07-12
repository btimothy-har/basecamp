# hub (Python portion)

`basecamp.hub` — the host-global daemon every session, agent, and observer connects to. A FastAPI app served over a Unix domain socket (`app.py`, run via `server.py`), a SQLite store (`store/`, at `~/.pi/basecamp/swarm/daemon.db` — the runtime dir keeps its legacy `swarm/` segment), the agent runner (`runner.py`, `process.py`, `run_result.py`), the service layer (`service/`), and the WS frame contract (`frames.py`), kept in lockstep with the TypeScript client + wire protocol in `pi/core/hub/` — see `pi/core/hub/protocol/PROTOCOL.md`.

Run as the daemon behind the `basecamp` CLI (entry point in `src/basecamp/cli.py`). Tests live in `tests/hub/`.
