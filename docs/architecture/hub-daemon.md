# Hub Daemon & Dashboard Topology

`basecamp.hub` is the host-global daemon every session and agent connects to. One process owns two isolated FastAPI apps:

- **Control app**: served only over `~/.pi/basecamp/swarm/daemon.sock` (tightened to `0600` after bind). It owns `/ws`, mutations, health, workstreams, private dashboard projections, and bootstrap nonce minting.
- **Read-only agents dashboard**: a separate app in a managed thread, pre-bound to fixed `127.0.0.1:47658`. It serves packaged assets and hardcoded snapshot/message proxies only; never the daemon app or a generic UDS route. Failure to bind or start it never stops the control app.

`dashboard/` owns in-memory nonce/session authentication, the TCP app and server lifecycle, the allowlisted stdlib UDS client, and the no-build packaged frontend assets. `store/` owns SQLite persistence and bounded read models at `~/.pi/basecamp/swarm/daemon.db`; `swarm/` owns agent runtime; `frames/` stays in lockstep with the TypeScript client and `docs/architecture/hub-protocol.md`.

`basecamp agents` starts or reuses the singleton hub, POSTs to the owner-only UDS for a 30-second one-time bootstrap URL, and opens the browser. The daemon holds a process-lifetime `flock` before touching the socket; TypeScript and Python clients additionally coordinate startup through the shared `daemon.spawn.lock` contract. Run the daemon through the `basecamp` CLI (entry point in `src/basecamp/cli.py`).

## Connection liveness and takeover

A node id admits one connection at a time, but that guard cannot be a bare rejection: a session that died uncleanly (kill, sleep/wake) leaves a half-open socket whose handler only notices the close on its next read or write. Three things resolve it together.

- **Transport keepalive**: uvicorn's stock transport keepalive closes a peer that stops answering protocol pings, in roughly forty seconds. It does not cover a peer whose transport still accepts bytes, the common shape of an unclean exit, so a duplicate register can sit behind a `duplicate_node_connection` rejection for that whole window.
- **Incumbent probe**: a duplicate register probes the incumbent and requires an answer. The probe is a `ping` frame carrying a fresh nonce; liveness means the matching `pong` came back within `_INCUMBENT_PROBE_TIMEOUT_S`. A live incumbent keeps its session and the newcomer gets the same rejection; only an unanswered probe yields the node id. **Blind takeover is deliberately not implemented**: an accidental resume against a working session must never displace it.
- **Generational claim**: waiting for a pong suspends, so the registration cannot simply claim the id afterwards; another register may have settled in between. `Registry.claim_connection` is a compare-and-set against the generation observed before the probe, and a racing registration is rejected rather than silently displacing the winner. Entries carry a monotonic generation on the way out too; `remove_connection` only clears the entry that is still its own, so a stale handler cannot remove or reap the connection that replaced it.

A completed write is deliberately *not* the probe signal: uvicorn's `WebSocketsSansIOProtocol` sets `writable` at construction and never clears it, so the send buffers into the transport without suspending and a frozen peer accepts the bytes exactly like a healthy one; a write-success check would report every incumbent alive and the takeover would never fire.

The probe is only trustworthy if the read loop is responsive, which is why `wait` and `message_status(wait_until_delivery)` execute as tracked `asyncio` tasks rather than inline: an inline wait would block its own socket for the full timeout, starving telemetry, dispatch, peer messages, and cancel, and delaying close discovery by exactly as long. `wait` therefore carries a `request_id` that the result echoes, which also makes concurrent waits on one socket unambiguous for the client.

## Agents dashboard architecture

`basecamp agents` first runs a Python port of the TypeScript hub ensure contract: the same `daemon.spawn.lock` path, exclusive `0600` `{pid, ts}` file, 30-second stale rule, protocol health gate, PID command validation, detached `basecamp hub` command, and timeout behavior. The daemon independently holds `daemon.server.lock` with nonblocking `flock` for its entire lifetime **before** touching the socket, so the one-hub invariant remains authoritative even if clients race or someone launches `basecamp hub` manually. Both spawn-lock owners verify the acquired file's inode before unlinking it.

Browser authentication is process-memory-only:

- The owner-only UDS mints a CSPRNG bootstrap nonce with a 30-second TTL; redemption is atomically single-use and creates a separate bounded 12-hour server-side browser session.
- The response sets a host-only `HttpOnly; SameSite=Strict; Path=/` cookie and returns a no-store `303` to `/`.
- Loopback HTTP cannot use `Secure`, and browser cookies are host-scoped rather than port-scoped: an accepted single-user-localhost trade-off, not a multi-user security boundary.
- Defense in depth: exact raw `Host` check, exact Origin when present, required `Sec-Fetch-Site` (`none`/`same-origin` only by route), no CORS, disabled TCP access/server/date headers, no-store responses, restrictive CSP/referrer/sniff/frame/opener/resource/permissions headers, and DOM construction through `textContent` rather than HTML sinks.

The dashboard uses a distinct safe global read model rather than exposing existing control/store rows:

- Structural roots are selected independently of descendant traversal; agent-free roots remain visible. Copilot mode takes classification precedence, then durable workstream attachment, then Root.
- Descendant traversal is cycle-safe, ask answerers/subtrees stay hidden, truncation is explicit, and all browser identity/routing uses public handles.
- Every live root is projected; disconnected history is a newest-first 24-hour prefix loaded five at a time to a 50-root ceiling, with at most one pin on the selected eligible root. The display window is query-time scope, never retention or cleanup.
- One cancellation-safe snapshot-projection worker runs at a time; overlapping refreshes fail fast as busy rather than queueing shared-executor store work.

`docs/architecture/hub-protocol.md` is the canonical source for exact bounds, endpoint fields, and privacy exclusions.

The frontend is a packaged, no-build application under `src/basecamp/hub/dashboard/assets/`: semantic HTML, ordered external CSS, and flat ES modules, with no external runtime request, framework, CDN, or client-side persistence. It polls only while visible, keeps the last safe in-memory snapshot on transient failure or busy refresh, uses public-handle hash routes, and fetches messages only for the selected agent. The compact in-Pi agent widget and workstream tools remain independent.
