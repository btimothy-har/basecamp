# hub (Python portion)

`basecamp.hub` is the host-global daemon every session and agent connects to. One process owns two isolated FastAPI apps:

- The control app is served only over `~/.pi/basecamp/swarm/daemon.sock`. `UdsServer` tightens it to `0600` after bind; it owns `/ws`, mutations, health, workstreams, private dashboard projections, and bootstrap nonce minting.
- The read-only agents dashboard is a separate app in a managed thread, pre-bound to fixed `127.0.0.1:47658`. It serves packaged assets and hardcoded snapshot/message proxies only—never the daemon app or a generic UDS route. Failure to bind or start it never stops the control app.

`dashboard/` owns in-memory nonce/session authentication, the TCP app and server lifecycle, the allowlisted stdlib UDS client, and the no-build HTML/CSS/ES-module assets. `store/` owns SQLite persistence and bounded read models at `~/.pi/basecamp/swarm/daemon.db`; `swarm/` owns agent runtime; `frames/` stays in lockstep with the TypeScript client and `pi/core/hub/protocol/PROTOCOL.md`.

`basecamp agents` starts or reuses the singleton hub, POSTs to the owner-only UDS for a 30-second one-time bootstrap URL, and opens the browser. The daemon holds a process-lifetime `flock` before touching the socket; TypeScript and Python clients additionally coordinate startup through the shared `daemon.spawn.lock` contract.

The dashboard query always returns live roots plus a five-at-a-time, 24-hour disconnected-root prefix capped at 50, through a public-handle-only safe projection. One cancellation-safe worker owns snapshot projection at a time; overlapping refreshes fail fast as busy instead of queueing more store work. `pi/core/hub/protocol/PROTOCOL.md` is the canonical source for its scope, fields, bounds, and exclusions.

Run the daemon through the `basecamp` CLI (entry point in `src/basecamp/cli.py`). Tests live in `tests/hub/`; dashboard model tests also run under `npm test`.
