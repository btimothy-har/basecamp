# pi-swarm daemon runtime

This package owns the Python async-agent daemon runtime.

It contains the FastAPI application, Unix-domain-socket server runner, protocol frame models, in-memory runtime registry, and SQLite persistence used by `basecamp swarm daemon`.

## Run lifecycle

Dispatched agents are spawned in their own process group so the daemon can tree-kill a run. Dispatched-run processes are cleaned up on dispatcher disconnect (after `BASECAMP_AGENT_DISCONNECT_GRACE_S`, default 3600s, unless the dispatcher reconnects), on explicit `cancel`, and on daemon startup (orphaned runs are reconciled to `failed` and their process groups best-effort killed). See `pi-swarm/protocol/PROTOCOL.md` for the frame- and status-level contract.
