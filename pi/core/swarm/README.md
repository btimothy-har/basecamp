# core/swarm — the agent-dispatch primitive

Core's adapter for Basecamp's async-agent runtime — a peer of [`core/hub`](../hub) (the daemon connection) that turns "there is a socket to the daemon" into "you can dispatch, wait on, message, and cancel agents." It is **substrate, not a feature**: multiple domains build on it, so it lives in `core` (registered by `registerCore` via `registerSwarm`, right after the hub connector) and is imported as `#core/swarm/agents/*`.

It rides entirely on `#core/hub`: the WebSocket transport, ensure-daemon, node identity, and the wire-protocol contract (`protocol/`) all live there. The Python daemon it talks to is `basecamp.hub` (`src/basecamp/hub/`); the server side of this primitive is `basecamp.hub.swarm`. The on-disk runtime path is `~/.pi/basecamp/swarm/`.

## What it owns (`agents/`)

- **Agent catalog** (`discovery`, `catalog`, `builtin/*.md`) — the basecamp-owned builtin agents (`worker`, `scout`, the review specialists), published to the core catalog registry (`#core/catalog`) as the `agents` capability type. Core can't enumerate these itself (they aren't pi-native), so the primitive supplies the provider; the definitions are its standard library.
- **Hub client** (`rpc` behind the `client` façade, `delivery`, `dispatch-retry`) — the agent request methods (dispatch/wait/ask/cancel/peer/message-status/list/run-summary) built on the `#core/hub` connection + frames. Defines no frame type and opens no socket.
- **Launch** (`launch`, `executor`, `model-resolution`, `run-result`) — builds the Pi CLI invocation and spawn spec for a dispatched agent, plus the run-result sidecar contract.
- **Reporting** (`reporter`, `event-summaries`) — the daemon run reporter that streams telemetry and persists results during a subagent run.
- **Tools** (`tools` + `tool/`) — the session-facing `dispatch_agent`/`ask_agent`/`cancel_agent`/`list_agents`/`wait_for_agent`/peer-message tools, gated by agent depth and top-level vs daemon-spawned role.
- **Observability** (`widget`, `view/`) — the active-agents widget and the read-only run/workstream HTTP views over the daemon.
- **Session surfaces** (`surfaces` → `index.ts`'s `registerSwarm`) — wires the tools, reporter, peer-delivery handler, and widget onto the (re)established hub connection, with reload-safe `processScoped` state.

## Consumers

The primitive has no slash command and no feature policy of its own. Two standalone feature domains build on it:

- **[`pi/code-review/`](../../code-review)** — the user-invoked `code-review` skill + `report_findings` tool.
- **[`pi/workstreams/`](../../workstreams)** — durable, repo-neutral workstream coordination.

Future agent-powered capabilities are expected to be new domains that consume `#core/swarm/agents/*` the same way.

## Agent lifecycle

Dispatched agents can be stopped with the `cancel_agent` tool, which cancels an agent you dispatched and terminates its process (subtree-only: you cannot cancel agents outside your dispatch tree). Agents are also reaped automatically when their dispatcher session ends and does not reconnect within `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default 3600s). See [`core/hub/protocol/PROTOCOL.md`](../hub/protocol/PROTOCOL.md).
