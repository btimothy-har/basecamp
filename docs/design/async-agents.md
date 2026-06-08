# Asynchronous Multi-Agent System — Design

**Status:** Phase 1 IMPLEMENTED (walking skeleton) · **Scope:** Design + status tracking for later phases · **Roadmap:** Phases 2–5 remain design targets

This document describes the target architecture for basecamp's asynchronous, collaborating subagents, coordinated by a global, single-host daemon. It captures the converged design, the decisions and rejected alternatives behind it, the risk register, and a phased roadmap whose first phase is a deliberately minimal walking skeleton.

It remains primarily a design artifact for later phases: Phase 1 is implemented, while the remaining target architecture in this document is roadmap/design work (§3 documents the existing synchronous behavior that this design replaces).

---

## 1. Problem statement

basecamp today runs subagents **synchronously**. The `agent` tool spawns a `pi --mode json -p` child process and the calling LLM blocks until that child exits, consuming its final message as the tool result. This is simple and predictable, but it has two structural limits:

- **The caller is blocked for the whole task.** A dispatch is a single, opaque, blocking call. The parent cannot dispatch work, keep reasoning, and collect results on its own schedule. Fan-out is bounded by an in-process run guard, and there is no way to start several units of work and rejoin them later.
- **There is no inter-agent collaboration.** A subagent is a leaf: it receives one task, runs to completion, and returns one string. Agents cannot message a peer, ask their supervisor a question mid-task, or be re-tasked while they retain their prior context. Each dispatch starts from nothing and ends permanently.

We want agents that can run **concurrently**, **persist their conversational thread across tasks**, and **collaborate** — message peers, escalate to a supervisor, and be re-tasked — while preserving the safety properties the synchronous model gives us for free (bounded nesting, serialized mutation of a shared worktree).

## 2. Goals and non-goals

### Goals

- **Asynchronous dispatch.** Dispatching an agent returns immediately with a handle; the caller continues working and rejoins results when it chooses.
- **Persistent agent identity.** An agent is a durable entity (a thread) that survives between tasks and can be re-tasked, not a one-shot process.
- **Collaboration.** Agents can exchange messages with permitted peers and escalate to a supervisor; results flow back to the dispatcher.
- **Central coordination.** A single coordinator owns the relationship graph, concurrency limits, mutation leases, and deadlock detection — things no per-session, in-process guard can enforce across the whole host.
- **Safety preserved.** Bounded nesting depth, serialized mutation of a shared worktree, and a ceiling on total concurrent agents.
- **No protocol coupling to pi internals on the coordinator.** The coordinator never parses pi's wire formats.

### Non-goals

- **No RPC / warm-process agents.** Agents are not long-lived resident processes exposing a call interface. (See Rejected Alternatives.)
- **No cross-machine / networked operation.** Single host only; the transport is a Unix domain socket.
- **No worktree-per-agent + merge.** Agents share one worktree, serialized by a lease — not isolated branches that are later merged.
- **No per-edit locking.** Mutation coherence is at the task grain, not the individual file-write grain.
- **No retained synchronous code path in the final architecture.** The system is async-always; synchronous behavior is recovered by an explicit wait primitive, not a parallel code path. (A transitional period where the old and new paths coexist is a roadmap concern — see §10.)
- **No automatic pruning** of agent threads or `.jsonl` files in v1. Cleanup is manual.

## 3. Current synchronous model

Grounded in the current code (`pi-extension/src/workflow/agents/`):

- **Dispatch and execution (`executor.ts`).** `spawnAgent()` builds a `pi --mode json -p` argv via `buildPiArgs()` and spawns it as a child process. Notable flags: `--model`, `--worktree-dir`, `--thinking`, `--session-dir` (the subagent's own session), `--no-prompt-templates`, `--read-only` (whenever the agent's run kind is not `mutative`), `--agent-prompt` (the persona, written to a file), `--tools` (a resolved allowlist), and `--no-skills` + an injected skill block when the agent declares specific skills. The parent reads the child's stdout, parses newline-delimited JSON events (`tool_execution_start`, `tool_execution_end`, `message_end`), and renders progress. The agent's **result is the last assistant message** ("last assistant message wins"); usage and tool calls are aggregated for display.
- **The `agent` tool (`tool.ts`).** Registered as a pi tool the LLM calls. It blocks on `spawnAgent()` and returns the child's final output as the tool result for immediate reasoning. Before running, it first requires that the `agents` skill has been invoked (`hasInvokedSkill("agents")`), then enforces two guards:
  - **Depth guard (`checkDepth`).** Reads `BASECAMP_AGENT_DEPTH` (default `0`) and `BASECAMP_AGENT_MAX_DEPTH` (default `DEFAULT_AGENT_MAX_DEPTH = 2`); throws if `depth >= max`. `buildAgentEnv()` copies all `BASECAMP_*` vars into the child and sets `BASECAMP_PARENT_SESSION`, `BASECAMP_PROJECT`, and an incremented `BASECAMP_AGENT_DEPTH`.
  - **Run guard (`beginAgentRun`).** An **in-process** state machine per parent session: any number of **named read-only** agents may run in parallel, but a **mutative** or **ad-hoc** agent must run **solo** (no other agent may be live). Mutative agents additionally require an active execution worktree (`workspace.activeWorktree.path`); without one the dispatch is rejected.
- **Lineage.** Parent/child lineage is carried only by the injected `BASECAMP_PARENT_SESSION` env var and the per-session state JSON; there is no central registry of runs or relationships.

**What this model gives us for free** — and what the async design must therefore preserve — is bounded nesting (the depth guard) and coherent mutation of the shared worktree (the run guard's "mutative runs solo" rule, which implicitly serializes writers). The async design replaces the in-process run guard with a central daemon, so these properties must be re-established explicitly (a concurrency cap and a mutation lease, respectively).

## 4. Target architecture

The synchronous, in-process model is replaced by a **global coordination daemon** plus **async-always agents**. The daemon is the single authority for relationships, limits, mutation leases, and message/result routing. Agents remain transient `pi --mode json -p` processes, but they now (a) persist their thread across tasks via their own `.jsonl` session file and (b) speak to the daemon over a WebSocket.

Two ideas anchor the whole design:

1. **The daemon never parses pi formats.** Each pi process loads the basecamp extension; the extension's TypeScript translates pi lifecycle events (`tool_execution_*`, `message_end`, `turn_end`) — plus an extension-detected run-completion signal — into basecamp's *own* WebSocket protocol. The daemon only ever sees basecamp frames. This removes the largest maintenance risk of a cross-language design — drift between pi's evolving wire format and a Python parser.
2. **An agent is a thread, not a process.** At rest, an agent is just a SQLite row plus a `.jsonl` file. "The agent persists" means its identity and conversation persist; the OS process is ephemeral and exists only while a task runs. Re-tasking spawns a fresh `pi --mode json -p` that resumes the agent's `.jsonl`.

### 4.1 Components

- **Top-level pi sessions** — the interactive sessions a user runs. Each loads the basecamp extension, which opens a WebSocket to the daemon at session start.
- **basecamp daemon** — a single, host-global Python process (FastAPI served by uvicorn over a Unix domain socket). It is coordinator (spawns agents), supervisor (owns the relationship/ACL graph), router (messages and result notifications), mutation-lease manager, and limit enforcer (depth + global concurrency). It exposes HTTP routes for read-only observability.
- **SQLite store** — the daemon's source of truth: agents, runs, relationships, leases, queued messages/results. Survives daemon restarts.
- **Transient agent processes** — `pi --mode json -p` children the daemon spawns per task. Each loads the basecamp extension and connects its own WebSocket back to the daemon.
- **`.jsonl` thread files** — each agent's pi session transcript. Async agents are spawned with `--session-dir` pointing at a **basecamp-managed durable location** (`~/.pi/agent/basecamp/agents/<name>/session/`), kept deliberately distinct from pi's default session store so an agent reads as a *distinct entity* rather than an ordinary, user-continuable session (§6.6). Persisted indefinitely (no TTL); resumed on re-task to continue the thread.
- **Shared worktree(s)** — the execution worktree(s) agents read and write, with mutation serialized by the daemon's per-worktree lease.

### 4.2 Component diagram

```
 Single host
 ────────────────────────────────────────────────────────────────────────────

  pi session (top-level)              pi session (top-level)
  ┌────────────────────┐              ┌────────────────────┐
  │ basecamp extension │              │ basecamp extension │
  │  • WS client       │              │  • WS client       │
  │  • pi-event→frame   │              │  • pi-event→frame   │
  └─────────┬──────────┘              └──────────┬─────────┘
            │  WS over UDS                        │  WS over UDS
            └──────────────────┬──────────────────┘
                               ▼
            ┌───────────────────────────────────────┐      HTTP over UDS
            │           basecamp daemon              │   GET /runs, /agents
            │        (FastAPI / uvicorn, UDS)        │◄──────────────────────
            │                                         │   (observability)
            │   coordinator · supervisor (ACL)        │
            │   router (messages + result pings)      │
            │   mutation-lease manager                │
            │   depth + global concurrency caps       │
            │              ┌──────────┐               │
            │              │  SQLite  │ agents, runs,  │
            │              │  store   │ leases, msgs   │
            │              └──────────┘               │
            └───────┬─────────────────────▲───────────┘
       spawn        │                     │  WS over UDS:
       pi -p        ▼                     │  telemetry, result, messages
            ┌────────────────────┐        │
            │  transient agent    │───────┘
            │  pi --mode json -p  │        resumes   ┌──────────────────┐
            │  + basecamp ext     │───────────────►  │ <agent-id>.jsonl │
            │   (WS client)       │                  │  thread file     │
            └─────────┬───────────┘                  └──────────────────┘
                      │  reads / writes (only while holding the lease)
                      ▼
            ┌────────────────────┐
            │  shared worktree    │
            └────────────────────┘
```

The sections that follow specify each layer: the transport and daemon startup (§5), the agent lifecycle and the TypeScript↔Python spawn contract (§6), collaboration, safety, and limits (§7), and finally risks, rejected alternatives, and the phased roadmap (§8–§10).

---

## 5. Transport, protocol & daemon startup

### 5.1 Transport

The system is single-host only. The only transport is a Unix domain socket (UDS): no TCP listener, no network path. The daemon socket is created with permissions `0600`, so the trust boundary is local-user only.

Connection model:

- One WebSocket per top-level session process to the daemon.
- One WebSocket per live transient agent process to the daemon.
- All connections are bidirectional/full-duplex: the daemon can push to connected processes, and processes can send frames upward.

The daemon also exposes read-only HTTP observability routes over the same UDS:

- `GET /runs`
- `GET /agents`

These routes are inspection-only (human/tooling visibility), not the control path.

### 5.2 Protocol — basecamp frames

The daemon speaks only basecamp frames. It never parses pi wire formats directly. Each top-level session and transient agent process loads the basecamp extension, and that TypeScript layer translates pi lifecycle events (`tool_execution_start`, `tool_execution_end`, `message_end`, `turn_end`) and an extension-detected run-completion signal into basecamp frames before sending.

This is the key ownership boundary: protocol translation stays in the extension, which eliminates drift risk from pi event-format evolution on the Python daemon side.

Frame taxonomy (design level):

| Frame category | Intent |
| --- | --- |
| Registration / handshake | On connect, provide process identity and protocol version/capability metadata. |
| Telemetry | Report tool/turn/run progress for live observability. |
| Result reporting | Report that a run completed and where the full result is stored. |
| Peer messages | Carry agent↔agent and top-level session↔agent communications. |
| Result pings | Lightweight "result ready" notifications (notify-then-fetch). |
| Control | Spawn requests, mutation lease requests, and `wait_for_agent` registrations. |

Every frame carries a protocol-version tag; compatibility is checked during handshake (§5.3). Detailed semantics for peer message vs result ping behavior, `wait_for_agent`, and mutation lease requests are specified in §7.

### 5.3 Daemon startup — the `session_start` ensure-daemon sequence

At `session_start`, the extension runs an ensure-daemon flow off the critical path: it must not delay the user's first prompt, and the UI shows a status indicator while initialization settles.

1. Resolve the fixed global UDS path (for example `~/.pi/agent/basecamp/daemon.sock`).
2. Send a health ping with a short timeout.
3. If the daemon is up, read its advertised protocol version and run handshake.
   - Compatible: proceed.
   - Incompatible: surface a clear error.
   - Do not restart the daemon automatically in this case.

   The daemon is host-global and may be serving other live sessions/repos (potentially on different basecamp versions); restarting it unilaterally would break unrelated active work.

4. If the daemon is not running, acquire a spawn lock (PID + timestamp) so concurrent session starts do not race and launch duplicates; start via the basecamp Python package entrypoint; wait-for-healthy with bounded retries; release lock.
5. Open this process WebSocket and register identity (env contract in §5.4).

```text
top-level session: session_start
        |
        v
resolve global UDS path
        |
        v
health ping (short timeout)
   | up? |
   |     |
  yes    no
   |     |
   v     v
read daemon version      acquire spawn lock (PID,timestamp)
+ run handshake          start daemon entrypoint
   |                     wait-for-healthy (bounded retries)
compatible?              release lock
   |                         |
  yes                        +---------+
   |                                   |
   +-----------------------------------+
               |
               v
       open WS + register identity
               |
               v
         normal frame traffic
```

### 5.4 Injected environment contract

The spawning extension and daemon rely on injected environment values.

| Variable | Status | Purpose |
| --- | --- | --- |
| `BASECAMP_PROJECT` | Existing | Project identity context for registration and routing. |
| `BASECAMP_PARENT_SESSION` | Existing | Parent linkage used to construct the relationship graph. |
| `BASECAMP_AGENT_DEPTH` | Existing | Current depth value used in depth cap enforcement. |
| `BASECAMP_AGENT_MAX_DEPTH` (default `2`) | Existing | Configured depth cap upper bound. |
| `BASECAMP_SESSION_NAME` | Existing | Session label for identity/observability. |
| `BASECAMP_DAEMON_UDS` | New | Daemon UDS path used for discovery/connection. |
| `BASECAMP_AGENT_ID` | New | Durable agent identity for runs/thread continuity. |
| `BASECAMP_SIBLING_GROUP` | New | Sibling-group identifier used by peer ACL checks. |
| `BASECAMP_AGENT_TITLE` | New | Deterministic, human-readable session title for an async agent — a parenthesized agent name (or `Agent` for ad-hoc) plus a compact task label. The spawned agent appends a `[<4hex>]` session-id suffix and applies it as its session name (§6.6). |

The daemon derives relationship graph membership and effective depth from these values. ACL and graph-rule details are defined in §7. Worktree identity is not a daemon-owned env value: it travels in the spawn spec (the `--worktree-dir` argument, §6.2) alongside basecamp's existing `BASECAMP_WORKTREE_DIR` / `BASECAMP_WORKTREE_LABEL` session env.

## 6. Agent lifecycle & the TS↔Python spawn contract

### 6.1 An agent is a thread, not a process

At rest, an agent is persisted state, not a running program: a row in the daemon's SQLite store plus its thread file (a `.jsonl` under the basecamp-managed durable session store, §6.6). It is not a resident process and retains no in-memory runtime state between tasks.

"The agent persists" therefore means two things persist: durable identity (`BASECAMP_AGENT_ID`) and conversation history (the thread file). Execution is provided by a transient agent process that exists only for one run and then exits.

Re-tasking the same agent always launches a fresh `pi --mode json -p` transient agent process that resumes the existing thread file and continues the same conversation.

### 6.2 The spawn spec (the TS↔Python contract)

The spawn spec is the central TypeScript↔Python contract. It is a structured launch descriptor authored by the basecamp extension (TypeScript) and persisted by the daemon per agent in SQLite. It fully determines how to launch a transient agent process:

- command + argv (the `pi --mode json -p ...` invocation and flags),
- environment block (the injected `BASECAMP_*` set described in §5.4),
- working directory (the repo root for async agents, not the active worktree — §6.6),
- resume slot (which thread file to continue),
- task/prompt slot (the task content for this run).

Ownership boundary (consistent with §5.2): the daemon executes the spawn spec opaquely with respect to pi semantics. All knowledge of pi flags and pi output formats remains in the TypeScript extension. The daemon does not construct pi argv from semantic fields and does not parse pi output.

The daemon's responsibilities are intentionally narrow:

- process lifecycle (spawn, track, reap),
- agent-id → thread file mapping (filling the resume slot with the correct path token, treated opaquely),
- substitution of the task/prompt slot for each run.

Because the spawn spec is persisted, an idle agent can be re-tasked without a fresh request from the originating top-level session: the daemon reuses the stored spawn spec, fills the new task/prompt slot and resume slot, and launches.

The resume slot and task/prompt slot are the spec's only mutable fields: they are explicit, named substitution points the daemon fills per run. Every other field (command, the remaining argv, env block, working directory) is immutable and opaque to the daemon. The daemon validates that both slots are present and populated before launching; a spec missing a slot is a spawn error, not a silent launch.

Semantic inputs encoded by the extension into each spawn spec (what varies per agent) include persona/agent-prompt, tool allowlist, model, thinking level, declared skills, worktree dir, read-only vs mutative run kind, and the env block. These mirror current `buildPiArgs` inputs; argv construction remains TypeScript-owned.

### 6.3 Run lifecycle: spawn → work → completion

A run is one transient agent process lifetime.

1. **Spawn.** The daemon launches a transient agent process from the stored spawn spec, resuming the agent's thread file. Cold-start overhead (extension load, prompt assembly, thread replay) is paid per run by design; a warm-process pool is rejected (see §9).
2. **Register + stream.** The child loads the basecamp extension, opens its WebSocket over UDS, registers identity, and streams telemetry frame updates (translated pi lifecycle events) for live observability.
3. **Completion.** When the extension detects run completion it sends a result-reporting frame. The run result is the last assistant message (same rule as today's executor: "last assistant message wins"). The daemon persists the full result, releases any mutation lease held by the run, and emits a result ping to the dispatcher. Delivery semantics remain notify-then-fetch (§7.2). Phasing note: persisting the result and resolving `wait_for_agent` are Phase 1; the *unsolicited push* of a result ping into an idle or streaming dispatcher is Phase 2 (§10), so in Phase 1 a dispatcher observes completion by joining via `wait_for_agent`.
4. **Backstop.** If the process exits without a result-reporting frame (crash, kill, non-zero exit), the daemon detects exit, marks the run failed, and resolves/notifies any `wait_for_agent` waiter. No waiter can block forever on a missing terminal signal.

   A symmetric case is the daemon itself restarting while runs are in flight. SQLite is the source of truth: on restart the daemon reconciles runs left in a non-terminal state, accepts reconnect-by-id from agent processes still alive (matched on `BASECAMP_AGENT_ID` + run id), and marks unrecoverable runs failed so their waiters resolve. The full reconciliation rules are a later-phase concern (§8, §10); Phase 1 relies on the process-exit backstop above.

```text
                 +--------------------+
                 |        idle        |
                 +----------+---------+
                            |
                            | spawn (from spawn spec + resume slot + task slot)
                            v
                 +----------+---------+
                 |      running       |
                 | register + frames  |
                 +-----+----------+---+
                       |          |
       result-reporting|          |process exit w/o result frame
             frame     |          |
                       v          v
             +---------+--+   +---+---------+
             | completed  |   |   failed    |
             | persist    |   | persist err |
             | release    |   | notify wait |
             | ping       |   +------+------+ 
             +------+-----+          |
                    |                |
                    +-------+--------+
                            v
                          idle
```

### 6.4 Re-tasking and messaging an idle agent

Re-tasking an existing agent is depth-neutral: it reuses the same node in the relationship graph and does not increase depth. Only creating a new child agent increases depth (subject to the depth cap).

If a peer message targets an agent with no live transient agent process, the daemon re-tasks that idle agent by respawning from its stored spawn spec and delivering the peer message as the task/prompt slot input. Live-agent message delivery and ACL policy are specified in §7.

### 6.5 Persistence and cleanup (v1)

Thread files persist indefinitely. pi enforces no TTL for sessions; removal occurs only when the `.jsonl` file is deleted. Cleanup is therefore a basecamp concern.

v1 decision: no automatic pruning of agents or thread files. Cleanup is manual only. The accumulation risk is noted in §8; a TTL sweep is deferred beyond v1 (§10).

The agent contract provides no reset/compact operation. To obtain a clean slate, create a new agent. Context-window pressure within a long-lived thread is handled by pi's own auto-compaction behavior.

### 6.6 Agent identity & session storage (Phase 1 refinements)

Making an async agent a *first-class persistent entity* (not a throwaway like a synchronous subagent) required three identity refinements, all on the async path only. The synchronous `agent` tool (§3) is intentionally untouched: its children are ephemeral one-shots that are never browsed or resumed, so worktree-derived identity and a temp session dir are correct for it.

- **Repo association.** An agent's repo identity is derived by pi from the process's startup cwd (`resolveGitInfo` runs `git rev-parse --show-toplevel` and takes `repoName` from the toplevel's basename). `dispatch_agent` therefore sets the spawn-spec working directory to the **repo root** (`workspace.protectedRoot ?? workspace.repo.root ?? launchCwd ?? cwd`), not the active worktree. The `--worktree-dir` argument still travels in the argv and auto-attaches the worktree at the agent's `session_start`, so `effectiveCwd` becomes the worktree and all file work lands there. Net effect: the agent's pi session is associated with the real repo (e.g. `basecamp`) — mirroring its parent — while still doing work in the shared worktree. (A synchronous subagent launched from inside a worktree resolves its identity to the worktree dir; that is harmless for an ephemeral one-shot and is left as-is.)

- **Deterministic titles.** Async agents run `pi --mode json -p` with no UI, so the interactive title model (gated on `hasUI`) never fires and they would otherwise show only a uuid-ish name. Instead, `dispatch_agent` builds a deterministic title — a `(<agent-name>)` prefix for a named agent, `(Agent)` for ad-hoc, plus a compact task-derived label — and passes it via `BASECAMP_AGENT_TITLE` (§5.4). The spawned agent appends its own session-id suffix `[<4hex>]` (the same format as interactive titles), applies it with `setSessionName` at `session_start` (not UI-gated), and registers it as its `session_name`, so the daemon's `agents.session_name` reflects the title rather than the agent uuid. No title-model call is made (agents are frequent and ephemeral; the task already describes the work), and no frame/protocol change is needed — the title rides existing env plus the register frame's `session_name`. Interactive top-level titling is unchanged.

- **Durable, distinct session store.** The agent's `.jsonl` thread is the basis of re-tasking (§6.4), so it must survive. Async agents are spawned with `--session-dir` pointing at a durable, basecamp-owned location under the daemon runtime dir (`~/.pi/agent/basecamp/agents/<name>/session/`, alongside `daemon.db`/`daemon.sock`). Two properties matter: it is **durable** (unlike `$TMPDIR`, which the OS clears and which would destroy resumability), and it is **distinct** from pi's default session store (`~/.pi/agent/sessions/--<cwd>--/`). Keeping agents out of the default store is deliberate — a session there is treated as an ordinary, user-continuable session and would clutter the user's session browser, whereas an async agent should read as a separate entity, resumed by the daemon (via its spawn spec / session path), not casually continued by a user. The synchronous tool keeps its ephemeral `$TMPDIR` session dir.

## 7. Collaboration, safety & limits

### 7.1 Relationship graph & ACL

The daemon is the authority for the relationship graph, derived from the injected environment contract in §5.4. Top-level sessions and agents are nodes in a **single id space**: a node's own id is `BASECAMP_AGENT_ID` (for a top-level session, its session id occupies the same field), and `BASECAMP_PARENT_SESSION` carries the parent node's id regardless of whether the parent is a top-level session or another agent. Parent/child edges are formed from those two ids; a sibling cohort is keyed by `BASECAMP_SIBLING_GROUP` for agents spawned together by one parent. The single id space is what lets an agent-parent and a session-parent be represented uniformly.

Access control is **DEFAULT-DENY** and enforced daemon-side on every peer message, spawn, and `wait_for_agent` registration. Visibility is limited to three directions only:

- upward to the caller's parent (escalation),
- downward to its descendants,
- lateral to its sibling group.

Everything else is denied. In particular, unrelated top-level session nodes are never peers: a top-level session has no parent edge, so top-level sessions (including sessions from different repos sharing the same host-global daemon) cannot enumerate, message, spawn against, or wait on each other's agents.

### 7.2 Two delivery disciplines

The design intentionally uses two different delivery disciplines:

1. **Peer messages are instantaneous and full.** A peer message is conversational traffic and is routed immediately as a full frame (never batched or coalesced). Recipient delivery is state-dependent:
   - recipient transient agent process mid-turn (streaming): steer into the current turn,
   - recipient has a live process but is idle/between turns: triggerTurn to wake it,
   - recipient has no live transient agent process: re-task from its spawn spec, using the message as the prompt input (§6.4).
2. **Agent results are notify-then-fetch.** On run completion, the daemon emits a lightweight result ping immediately (never batched or coalesced). The ping is awareness only; full run output is persisted per §6.3 and fetched later by the dispatcher on dispatcher-controlled timing.

Dispatcher delivery for a result ping follows the same process-state rule: mid-turn is steered, idle is awakened via triggerTurn. This is the mechanical equivalent of immediate delivery in pi's model: steer applies only during a live turn, while idle delivery requires starting a turn.

Recipient/dispatcher state maps to a delivery action as follows:

| Target state | Peer message | Result ping |
| --- | --- | --- |
| Live process, mid-turn | steer into the current turn | steer the ping into the current turn |
| Live process, idle between turns | triggerTurn to wake it | triggerTurn to wake it |
| No live process | re-task from spawn spec, message as prompt (§6.4) | n/a — a result ping always targets a live dispatcher |

Implementation boundary from §5.2 applies: the extension performs these actions through pi's ExtensionAPI (`sendMessage` / `sendUserMessage` with `deliverAs: steer | followUp | nextTurn`, plus turn-triggering). The daemon routes frame traffic and does not call pi APIs.

Trade-off: waking an idle dispatcher on every result ping can interrupt active typing. The design chooses immediacy anyway because the result ping is tiny and non-committal, and consumption remains explicitly dispatcher-controlled.

### 7.3 `wait_for_agent` — the composable join

`wait_for_agent` is the explicit join primitive in an async-always model. Dispatch never blocks by itself; a caller that wants synchronous behavior opts in by waiting on one or more handles.

Supported join modes:

- **wait-ALL**: resume once after every listed handle has completed,
- **wait-FIRST**: resume when the first listed handle completes.

wait-ALL over multiple handles is the ergonomic fan-out/join shape: the caller blocks once and resumes once with a complete set, instead of being reawakened per child completion.

Execution semantics:

- the tool call blocks internally until the daemon signals completion according to the selected mode,
- timeout is supported,
- user abort (Ctrl+C) is honored,
- the §6.3 crash backstop guarantees no indefinite wait when a transient agent process exits without a terminal result frame.

Relationship to result ping (§7.2): result ping is unsolicited immediate awareness; `wait_for_agent` is explicit synchronization. They are complementary, not competing. A caller may ignore result pings and join solely via `wait_for_agent`.

### 7.4 Mutation lease & deadlock detection

The daemon owns a per-worktree mutation lease. Acquisition timing: a mutative run acquires the worktree's lease at **run admission** — the daemon grants the lease as a precondition of launching the run, so the transient agent process never begins work without holding it. If the lease is unavailable the mutative run **queues** at admission (subject to the deadlock check below) rather than launching and blocking mid-task. The run holds the lease for its full task and releases it on completion or failure. Read-only runs never acquire the mutation lease and can run concurrently.

The full-task hold is required for correctness. Real changes are read-modify-write sequences spanning multiple steps/files against one git index/HEAD. Per-edit locking permits interleaving between one writer's read and later write, which allows lost updates and incoherent composite diffs. Whole-task ownership prevents that class.

Stale reclaim is built in: lease metadata includes owner PID and timestamp. A lease is reclaimed if PID liveness fails or timestamp TTL expires, so a crashed holder cannot block a worktree indefinitely.

Whole-task lease holds plus cross-agent waits can deadlock. Worked example:

1. Parent dispatches mutative agent A in worktree W; A is admitted and acquires W's mutation lease.
2. A blocks on an **escalation** — a peer message to its parent that A waits on (§7.1 upward edge, §7.2).
3. Parent dispatches mutative agent B in W to answer.
4. B's admission requires W's mutation lease, which A holds, so B would queue.
5. Cycle forms: A waits on parent; parent waits on B; B waits on A's lease.

```text
A holds lease(W)
A -> waits on Parent
Parent -> waits on B
B -> waits on lease(W) held by A

Cycle: A -> Parent -> B -> A
```

The daemon is the single place that observes both lease ownership and wait edges (`wait_for_agent`, ask/contact_supervisor, lease requests), so it maintains the global wait-for graph. Any new edge that would close a cycle is rejected immediately with a diagnostic (for example: "would deadlock on worktree W held by A; A is blocked on you"). Enforced rule: an agent holding a mutation lease may not block on a dependent that must acquire that same worktree's mutation lease.

### 7.5 Limits: depth cap + global concurrency cap

Two independent limits are enforced by the daemon:

- **Depth cap** (tree height), default `2`: evaluated from the relationship graph. `BASECAMP_AGENT_DEPTH` remains a fast local pre-check/fallback, but daemon graph validation is authoritative. Over-cap child creation is rejected with a clear error. Re-tasking an existing agent is depth-neutral (§6.4).
- **Concurrency cap** (tree breadth): a host-global ceiling on simultaneously-live transient agent process count. Spawn requests beyond the cap queue until capacity is available.

The concurrency cap is new and required by async-always operation. The prior in-process run guard implicitly serialized much of execution; once dispatch is non-blocking, breadth pressure becomes the dominant host risk (CPU, memory, and process count). Only the host-global daemon can enforce that limit across all top-level session processes and repos.

Both limits are configurable tunables. They are complementary: depth cap bounds recursion height in the relationship graph, while concurrency cap bounds aggregate parallel width.

## 8. Risks & mitigations

| Risk | Mitigation | Residual / notes |
| --- | --- | --- |
| Fan-out/join token cost: the dispatcher being woken once per result ping can be expensive at high fan-out. | Prefer `wait_for_agent` wait-ALL (§7.3) so the caller resumes once with a complete set; the agents skill should teach "dispatch → end turn or wait-all." | Result ping remains immediate awareness (§7.2); callers that want low wake churn should join explicitly. |
| Daemon crash mid-run: in-flight runs orphan and waiters could stall. | SQLite is the source of truth; on restart, the daemon reconciles non-terminal runs, accepts reconnect-by-id, and marks unrecoverable runs failed (stale-run reconciliation), combined with the §6.3 process-exit backstop. | Short recovery windows are expected during restart; terminal state remains deterministic. |
| Silent agent failure / hang: a transient agent process may wedge without producing a result frame. | §6.3 backstop handles process exit failures; `wait_for_agent` timeout (§7.3) bounds caller wait. | A wedged-but-alive process with no exit and no result relies on timeout policy. |
| Context flooding: many or large results can overrun dispatcher context. | Notify-then-fetch (§7.2b): result pings are tiny; full payloads are persisted (§6.3) and fetched on demand. | Dispatcher behavior must continue to avoid eager bulk fetch by default. |
| Interactive wake disruption: waking an idle dispatcher can interrupt active typing. | Accepted trade-off (§7.2) for immediacy of result ping and peer message delivery. | Revisit with an editor-empty guard if user friction is high. |
| TS↔Python protocol drift: two language runtimes implement one frame protocol. | Keep a single schema source for frames; add a contract test that boots the real daemon and exercises protocol frames end-to-end; enforce protocol-version handshake (§5.3); pin the pi version for spawn flags. | Compatibility work is continuous as frames evolve. |
| Daemon version skew across repos: one host-global daemon can serve sessions from different basecamp versions. | Version handshake on connect; incompatible clients error loudly; never auto-restart a shared daemon (§5.3). | Mixed-version hosts require explicit operator coordination. |
| Local-user trust boundary: UDS is reachable by same-user processes even when ACL blocks visibility. | UDS file permissions `0600`; daemon-side default-deny ACL (§7.1). | Same-user processes are trusted by threat model (local dev tool). |
| Cold-start / replay latency: each run pays extension load, prompt assembly, and thread file replay (§6.3). | Accepted in v1; warm pool deferred to decisions/roadmap (§9, §10). | Throughput tuning focuses on caps/queueing first, not residency. |
| Unbounded accumulation: no pruning in v1 means agents and thread file artifacts grow over time. | Keep v1 manual cleanup; artifacts are expected to be small; evaluate TTL sweep later (§10). | Long-lived environments may require periodic operator hygiene. |
| Concurrency-cap queueing: bursts above the cap produce queue delay. | Make the concurrency cap tunable; add observability for queue depth and wait time (§10). | Latency under burst is a deliberate trade for host stability. |
| Migration risk: removing synchronous path touches `executor.ts`, `tool.ts` run guard, partial-render path, and agents skill. | Sequence migration by phase so guarantees are never absent; remove the in-process run guard only after mutation lease + concurrency cap are in place centrally. | Temporary implementation overlap is acceptable during phased rollout. |

## 9. Decisions & rejected alternatives

### 9.1 Decisions (converged)

- Agents remain transient `-p` executions; persistence is the agent identity + thread file, not a resident process.
- Coordination is centralized in a Python/FastAPI daemon over UDS with SQLite as system-of-record for agents, runs, relationships, and leases.
- TypeScript translates pi lifecycle events into basecamp frame traffic; the daemon is protocol-agnostic to pi wire formats.
- Connectivity model is one WebSocket per top-level session and per transient agent process; HTTP routes are read-only observability.
- Execution model is async-always; synchronous behavior is expressed via `wait_for_agent`.
- Delivery uses two disciplines: full peer message delivery and notify-then-fetch result ping.
- ACL is daemon-enforced and derived from injected environment + relationship graph (default-deny).
- Message to an idle agent triggers respawn/re-task from stored spawn spec.
- Shared-worktree mutation safety uses a whole-task mutation lease plus daemon-side deadlock-cycle rejection.
- The depth cap is retained; a host-global concurrency cap is added.
- v1 includes no automatic pruning and no reset/compact operation.
- Daemon start is wired into `session_start` ensure-daemon with compatibility handshake.

### 9.2 Rejected alternatives

- **RPC / warm-process agents.** Their only strong benefit is in-memory residency; that conflicts with the "not in memory at rest" requirement. Transient agent process execution plus thread file resume preserves continuity without resident workers.
- **Flat broker (reference style) instead of a central daemon.** A flat router cannot reliably own ACL, a host-global concurrency cap, mutation lease state, or deadlock detection over the wait-for graph. Those controls require a single coordinator with full graph visibility.
- **Daemon parses pi formats.** That couples Python coordination logic to pi's changing event/wire formats. TS-side translation isolates that change surface (§5.2).
- **Worktree-per-agent + merge.** It shifts collaboration cost into merge/conflict management and divergent trees. A shared worktree plus mutation lease preserves one coherent state.
- **Per-edit locking.** It does not protect read-modify-write sequences and reintroduces races (§7.4). Whole-task holding is the selected safety boundary.
- **Retained synchronous code path.** Parallel sync+async implementations would duplicate behavior and drift over time. Async-always with `wait_for_agent` recovers blocking semantics with one path.
- **Automatic pruning in v1.** It adds lifecycle policy complexity early without proven need; thread file artifacts are expected to be small. Manual cleanup now, TTL sweep later.

## 10. Phased roadmap

- **Phase 1 — IMPLEMENTED walking skeleton.** Delivered components: daemon (`basecamp daemon`), extension daemon client + `dispatch_agent` / `wait_for_agent`, and shared frame protocol fixtures under `protocol/`. Goal was to prove the end-to-end spine with one persistent agent identity and asynchronous run completion.
  - In scope: a single frame-schema source of truth + a daemon contract test (the protocol exists from Phase 1); `session_start` ensure-daemon + WebSocket handshake (§5.3); daemon spawns one transient agent process from a TypeScript-authored spawn spec (§6.2); async dispatch returns a handle immediately; telemetry + result reporting over WebSocket (§6.3); `wait_for_agent` for a single handle and wait-ALL over multiple handles (§7.3); process-exit crash backstop; SQLite persistence for agents/runs; async-agent identity refinements — repo-root spawn cwd, deterministic titles, and a durable/distinct session store (§6.6); depth cap retained. The existing in-process run guard (§3) also stays in place (see the sequencing note), so breadth remains bounded even though the global concurrency cap is not yet built.
  - Explicitly out of scope: peer message, ACL enforcement, mutation lease/deadlock detection, host-global concurrency cap, HTTP observability polish, re-task-on-message behavior, wait-FIRST joins, and the unsolicited result-ping push (in Phase 1 the dispatcher observes completion by calling `wait_for_agent`).
  - Acceptance criteria:
    - `session_start` produces a healthy daemon connection (spawn if absent, reuse if present, complete version handshake) without blocking first prompt availability.
    - The `agent` tool dispatches asynchronously and returns a run handle immediately.
    - A transient agent process executes, streams telemetry, and reports a result that the daemon persists.
    - `wait_for_agent` blocks and returns results for both a single handle and wait-ALL across two handles.
    - A deliberately crashed transient agent process resolves its waiter through the backstop (no indefinite wait).
    - The existing depth cap still rejects over-depth spawn attempts.

- **Phase 2 — Collaboration.** Goal: establish relationship graph + default-deny ACL (§7.1), peer message routing across all three recipient states including re-task-on-message for idle recipients (§7.2a, §6.4), and result ping notify-then-fetch wake behavior (§7.2b).

- **Phase 3 — Mutation safety.** Goal: ship per-worktree whole-task mutation lease with stale reclaim and daemon-side deadlock cycle rejection using the global wait-for graph (§7.4).

- **Phase 4 — Limits & scale.** Goal: add host-global concurrency cap enforcement, spawn queueing, and tunable limit configuration (§7.5).

- **Phase 5 — Observability & migration cleanup.** Goal: complete HTTP `/runs` and `/agents` observability (§5.1), rework partial render flow so telemetry is daemon-sourced (not direct child stdout), remove the synchronous execution path and in-process run guard after central guarantees are in place, rewrite the agents skill, and add TS↔Python frame contract tests.

Phase boundaries are for safe sequencing. The existing in-process run guard (§3) stays active through Phases 1–4, so its breadth/serialization guarantees are never absent; it is removed only in Phase 5, after the mutation lease (Phase 3) and the global concurrency cap (Phase 4) restore those guarantees centrally. Phase 1 is therefore additive — it introduces the async spine alongside the current synchronous path rather than replacing it.

---

## Glossary

Shared vocabulary; used consistently throughout this document.

- **Daemon** — the single host-global basecamp coordination process (FastAPI/uvicorn over a Unix domain socket).
- **UDS** — Unix domain socket; the only transport. Local-user only (filesystem permissions); no TCP, no network.
- **Top-level session** — an interactive pi session a user launched directly. Has no parent in the relationship graph.
- **Agent** — a durable entity: a SQLite row + a `.jsonl` thread. Persists between tasks; not a process.
- **Transient agent process** — the ephemeral `pi --mode json -p` child that runs a single task for an agent, then exits.
- **Thread file** — an agent's pi `.jsonl` session transcript, resumed on re-task to continue its conversation.
- **Spawn spec** — the structured, TypeScript-supplied description the daemon uses to launch a transient agent process (persona, tools, model, worktree, env).
- **Frame** — a message in basecamp's own WebSocket protocol. The daemon speaks only frames; the extension translates pi events into frames.
- **Run** — one execution of a task by an agent (one transient process lifetime), tracked in SQLite.
- **`wait_for_agent`** — the composable blocking tool that lets a caller rejoin one or more agents' results on demand (the async-world replacement for synchronous dispatch).
- **Peer message** — instantaneous, full-content communication between permitted agents/sessions; delivered into a live recipient (steer/triggerTurn) or by re-tasking an idle recipient (§7.2).
- **Result ping** — a lightweight "result ready" notification; the dispatcher fetches the full result on its own terms (notify-then-fetch).
- **Mutation lease** — the daemon-owned, per-worktree lock a mutative task holds for its full duration to keep the shared worktree coherent.
- **Relationship graph** — the daemon's parent/child + sibling-group model, derived from injected env, used for ACL and depth.
- **Depth cap** — the maximum nesting depth of the spawn tree (default 2), enforced by the daemon from the graph.
- **Concurrency cap** — the global ceiling on simultaneously-live agent processes; excess spawns queue.
