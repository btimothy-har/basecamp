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

## Agent execution posture

Every dispatched agent runs in its **own transient git worktree** with the uniform toolset (including `write`/`edit`); the posture is anchored on the **deliverable**, not the tools (issue #310, Phase 1 as revised after its independent review). Persona frontmatter `deliverable: true` — only `worker` — marks runs that mint a branch; every other persona, ad-hoc run, and ask is **report-only**: a branchless detached workspace whose report is the deliverable. Deliverable runs branch (`agent/<handle>`, worktree per run `agent-<runToken>/<name>`) from a **clean parent HEAD only** — a dirty parent fails the dispatch with commit-first guidance — so integration is always a plain `git merge` and no snapshot ever enters branch topology. A retask continues the agent's outstanding branch (memory and tree never contradict); a branch already merged into the parent/default branch is deleted eagerly at provision; a *fresh* dispatch that finds a pre-existing branch fails rather than adopting foreign work. Report/ask workspaces detach at the parent's HEAD or a **snapshot commit** of its dirty state (throwaway `GIT_INDEX_FILE` seeded from HEAD; the parent untouched), so reviewers see uncommitted WIP; asks detach at the ask target's branch tip when one exists. Setup hooks (`environments.setup`) run blocking-but-nonfatal on deliverable and report workspaces; asks skip them. **Capability follows workspace**: a non-repo session has no wall, so its dispatches get a report-only toolset (no `write`/`edit`). **Worktree-state restore is human-only** — daemon-spawned runs never re-attach a saved worktree (a forked ask answerer would otherwise adopt the ask target's live worktree).

**Commits are the only durable output of a run** (this replaced "never force-remove post-execution work"). The daemon owns the backstop chain: run-exit reap, then restart reconcile (nonterminal rows and terminal rows whose recorded workspace survived), both force-removing the workspace and deleting the branch only when this run minted it and it gained no commits past its recorded base OID — force is gated on the v27 spec fields, so pre-upgrade rows keep non-force removal, and teardown is skipped when a run's process group cannot be verified dead. The agent backstop is **fully daemon-owned**: after run-exit reap and restart reconcile, a periodic daemon sweep (`src/basecamp/hub/swarm/sweep.py`) reclaims integrated or branchless agent residue, breaks agent-run locks only past a staleness age (the lock reason carries a timestamp), and deletes integrated orphan `agent/*` branches (local `merge-base --is-ancestor` only), never touching unintegrated commits — so a never-restarted daemon cannot leak. The TypeScript session-start sweep no longer touches `agent/*`; it owns the session tier (see Worktree Design). The primary integrates by `git merge agent/<handle>`. Dispatched deliverable runs get a teardown-aware dirty reminder; branchless runs are exempt (scratch by design); primary sessions keep the advisory commit reminder. The worktree is the isolation boundary, enforced by the workspace guard's `allowed_dirs` rule; `bash` is deliberately retained and is **not** a mutation sandbox — the workspace, not the toolset, is the wall. Independently, the workspace `tool_call` guard hard-blocks structured `write`/`edit` to the protected main checkout even when a subagent has no active worktree.
