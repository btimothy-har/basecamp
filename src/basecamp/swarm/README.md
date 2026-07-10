# swarm (Python portion)

`basecamp.swarm` — the async-agent daemon. A FastAPI app served over a Unix domain socket (`app.py`, run via `server.py`), a SQLite store (`store/`, at `~/.pi/basecamp/swarm/daemon.db`), the agent runner (`runner.py`, `process.py`, `run_result.py`), the service layer (`service/`), and the WS frame contract (`frames.py`), kept in lockstep with the TypeScript client in `swarm/ts` — see `swarm/protocol/PROTOCOL.md`.

Started with `basecamp swarm` (entry point in `src/basecamp/cli.py`). Tests live in `tests/swarm/`.
