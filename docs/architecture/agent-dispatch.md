# The Agent-Dispatch Model

Core's adapter for Basecamp's async-agent runtime, a peer of `core/hub` (the daemon connection) that turns "there is a socket to the daemon" into "you can dispatch, wait on, message, and cancel agents." It is **substrate, not a feature**: multiple domains build on it, so it lives in `core` (registered by `registerCore` via `registerSwarm`, right after the hub connector) and is imported as `#core/swarm/agents/*`.

It rides entirely on `#core/hub`: the WebSocket transport, ensure-daemon, node identity, and the wire-protocol contract all live there. The Python daemon it talks to is `basecamp.hub`; the server side of this primitive is `basecamp.hub.swarm`. The on-disk runtime path is `~/.pi/basecamp/swarm/`.

## What it owns

- **Agent catalog**: the builtin agents (`scout`, the review specialists), published to the core catalog registry. Core can't enumerate these itself (they aren't pi-native), so the primitive supplies the provider.
- **Hub client**: the agent request methods (dispatch/wait/ask/cancel/peer/message-status/list/run-summary) built on the `#core/hub` connection and frames. Defines no frame type and opens no socket.
- **Launch**: builds the Pi CLI invocation and spawn spec for a dispatched agent. An unresolvable model alias inherits the parent model rather than failing the child launch; a sandbox opt-out propagates to a child only as a whole, never via env alone.
- **Reporting**: the daemon run reporter that streams telemetry and persists results during a subagent run.
- **Tools**: the session-facing `dispatch_agent` / `ask_agent` / `cancel_agent` / `list_agents` / `wait_for_agent` / peer-message tools, gated by agent depth and role.
- **Observability**: the active-agents widget and the read-only run/workstream HTTP views over the daemon.
- **Session surfaces**: wires the tools, reporter, peer-delivery handler, and widget onto the (re)established hub connection, with reload-safe state.

## Consumers

The primitive has no slash command and no feature policy of its own. Two feature domains build on it:

- **[`pi/code-review/`](../../code-review)**: the primary-only `/code-review` prompt command, its authoritative model-invocable skill, and the `report_findings` tool.
- **[`pi/workstreams/`](../../workstreams)**: durable, repo-neutral workstream coordination.

## Agent lifecycle

`cancel_agent` stops an agent you dispatched and terminates its process (subtree-only: you cannot cancel agents outside your dispatch tree). Agents are reaped automatically when their dispatcher session ends and does not reconnect within `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default 3600s). See [PROTOCOL.md](hub-protocol.md).

## Postures

Every dispatched agent runs in its **own transient git worktree**, and the posture is anchored on the **deliverable**, not the tools:

- **Deliverable** (ad-hoc dispatches, no `agent`): mints an `agent/<handle>` branch from a **clean parent HEAD only** (a dirty parent fails the dispatch with commit-first guidance), so integration is always a plain `git merge` and no snapshot ever enters branch topology. A retask continues the agent's outstanding branch; a branch already merged is deleted eagerly at provision; a *fresh* dispatch that finds a pre-existing branch fails rather than adopting foreign work.
- **Report-only** (named personas and asks): a branchless detached workspace whose report is the deliverable. It detaches at the parent's HEAD or a **snapshot commit** of its dirty state (the parent untouched), so reviewers see uncommitted WIP; asks detach at the ask target's branch tip when one exists.

Setup hooks (`environments.setup`) run blocking-but-nonfatal on deliverable and report workspaces; asks skip them. **Capability follows workspace**: a non-repo session has no isolation wall, so its dispatches get a report-only toolset (no `write`/`edit`). **Worktree-state restore is human-only**: daemon-spawned runs never re-attach a saved worktree (a forked ask answerer would otherwise adopt the ask target's live worktree).

## Teardown

**Commits are the only durable output of a run.** The daemon owns the full backstop chain: workspaces are removed at run exit, reconciled after a restart, and swept periodically, deleting a branch only when this run minted it and it gained no commits past its base. The workspace, not the toolset, is the isolation wall: `bash` is retained and is **not** a mutation sandbox, while the workspace guard hard-blocks structured `write`/`edit` to the protected main checkout. For the lease protocol and full teardown matrix, see [Worktree Lifecycle & Teardown](worktree-lifecycle.md).
