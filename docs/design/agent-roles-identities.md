# Agent Roles & Identities — Design

**Status:** PROPOSED · foundation pass (the **identity layer**); the scoping-ergonomics surfaces that ride on it are a follow-up (§11). · **Scope:** Rework the hub's node-identity so it is a rich, consistent substrate for *scoping* the open agent mesh. Redefine node `kind` = `agent | worker` on an explicit launcher flag; promote **repo / worktree / workstream** to first-class identity; **delete** the `product_role` / `agent-role` seam (executes [#244](https://github.com/btimothy-har/basecamp/issues/244)) and **reberth** its one signal on workstream membership; **drop** the mutative/`run_kind` guards; add **soft, single-TTL** agent expiry. Identity + lifecycle only — **no new contact deny-rules, no scoping UI in this pass.** · **Extends:** [async-agents.md](./async-agents.md) (the daemon + the ACL), [hub-core-connector.md](./hub-core-connector.md) (identity → `core/hub`), [swarm-core-primitive.md](./swarm-core-primitive.md) (the primitive → `core/swarm`). · **Executes (partially):** [#244](https://github.com/btimothy-har/basecamp/issues/244) — removes the `agent-role` *seam*, but **rejects its core thesis**: the workstream-vs-plain distinction is *kept and promoted* to a real workstream **assignment** (agents operate in an assigned workstream), not deleted. The handoff signal moves from the vestigial label onto real membership.

---

## 1. Problem statement

The hub connection went universal ([hub-core-connector.md](./hub-core-connector.md) §1): **every** top-level session and **every** spawned agent now registers with the daemon, whether or not it ever dispatches. And **contact is an open any→any mesh** — `message_agent` / `ask_agent` resolve a target purely by public handle, gated only by `PolicyMixin._can_contact_by_public_handle` (`src/basecamp/hub/store/policy.py:114-125`), which checks nothing but "does the target expose a handle." That openness is **intended** and is not in question here.

What the mesh lacks is a way to make itself *livable*. The only richly-modeled relationship on a node is the spawn tree (`parent_id` / `sibling_group` / `depth`), so the only lens anyone can offer is "my tree vs. not my tree." The dimensions people actually want to scope by are either dropped, unjoined, or vestigial:

- **repo is thrown away at the hub boundary.** `BASECAMP_REPO` (the canonical `<org>/<name>` identity) is set on `process.env` (`pi/core/project/workspace/runtime.ts:70`) but `deriveDaemonIdentity` never reads it (`pi/core/hub/identity.ts:43-67`). The only repo trace on an agent row is the raw `cwd`.
- **workstream membership lives in a side table** (`workstream_agents`, `src/basecamp/hub/store/workstreams/schema.py:32-42`) that is never joined into the roster or the ACL.
- **the one "role" label is vestigial.** `product_role` has a single registrant returning a single value, `"workstream_agent"` (`pi/workstreams/start.ts:255`) — the subject of #244.

Three accretions from the pre-mesh era clutter the model further: the `product_role` provider seam (`pi/core/agent-role.ts`); the `mutative`-vs-`read-only` `run_kind` and its solo/lease guards (predating the daemon *and* the mesh); and an **unbounded roster** with no expiry ([async-agents.md](./async-agents.md) §6.5).

**Identity is the substrate every scoped view filters on.** Fix it first, and the lenses become almost free; skip it and every view is stuck at the tree.

## 2. Direction — one open mesh, many lenses

The converged position: **keep contact open (any→any by handle); express "so it's not excessive" as ergonomic *lenses* over the roster, never as walls.** Filtering is a *view* concern (which nodes do I show / group / mute), not an *ACL* concern (who may I talk to). We do **not** touch `policy.py`.

That makes this pass entirely about the top of the pipeline — what a node asserts about itself at register — plus keeping the roster clean so the lenses read something honest:

```
LAUNCH ─ env: BASECAMP_REPO · WORKTREE_LABEL · RUN_ID · USER_FACING
   │
   ▼
IDENTITY (identity.ts)   who/where ─ kind(agent|worker) · handle · parent
   │                     facets    ─ repo · worktree · workstream · is-ws-agent
   │                     lifecycle ─ last_seen · status · expires (1 TTL, soft)
   ▼
REGISTER frame ──► agents row  ◀── the roster: single source of truth
   │
   ├─► TREE (parent/sibling/depth) → discovery · wait · cancel   [scoped — unchanged]
   └─► MESH (handle → handle)      → message · ask                [open  — unchanged]
                   │
                   ▼
        SCOPING LENSES = filter the roster by facet
        (repo · workstream · kind · subtree) → noise control, never denial
```

A node's identity decomposes into three groups: a **stable core** (who / where in the tree), **scoping facets** (how you group), and **lifecycle** (join → idle → expire).

## 3. Goals & non-goals

### Goals
- **Redefine `kind` = `agent | worker`** — `agent` = user-facing (a human session is attached), `worker` = fully backgrounded — founded on an **explicit `BASECAMP_USER_FACING` launcher flag**, read by the extension at register.
- **Promote `repo`, `worktree`, `workstream` to first-class identity** (facets on the `agents` row), plus a derived **`is_workstream_agent`**; keep `parent_id` (who-spawned) as-is.
- **Delete the `product_role` / `agent-role.ts` seam** (executes #244); **reberth `is_workstream_agent`** on workstream membership; **repoint the handoff worktree-reuse consumer** onto it.
- **Drop `run_kind` and the mutative / solo / read-only guards.**
- **Add soft, single-TTL, per-row agent expiry**; the row is retained.

### Non-goals
- **No new contact boundaries.** The mesh stays open; `policy.py` and the tree-scoped `discovery` / `wait` / `cancel` are untouched.
- **No scoping UI this pass.** The dashboard filters / `list_agents` scoping that consume these facets are the follow-up (§11) — this pass only makes the facets exist and be consistent.
- **No protocol single-source-of-truth / codegen** (still deferred, per [hub-core-connector.md](./hub-core-connector.md) §10) — though the frame *does* change here (§10), so the three hand-maintained copies move together once.

## 4. `kind` — agent vs worker

The distinction is **user-facing vs. backgrounded**, and it is founded on an **explicit signal the launcher stamps**, not inferred:

- `agent` — a human session is attached (the interactive launcher sets `BASECAMP_USER_FACING=1`).
- `worker` — fully backgrounded; the daemon/dispatch path spawns it and does **not** set the flag.

**Why an explicit flag and not `hasUI` / json-mode.** `ctx.hasUI` is `false` in print/JSON mode (`pi/engineering/skills/pi-development/references/EXTENSIONS.md:215`) — a *rendering* concern, not an identity one. A headless top-level automation run (`pi -p` at depth 0) would misclassify as a worker under a json-mode proxy, and the companion already conflates the two by gating panes on `hasUI && depth===0` (`pi/companion/panes/provider.ts:23`). The launcher, by contrast, *knows* which kind it is spawning. `hasUI` may still be carried as a separate **`attended`** boolean (is a human watching *right now*), decoupled from the structural `kind`.

**Change in `identity.ts`.** The role derivation moves off depth — today `const role = safeDepth > 0 ? "agent" : "session"` (`pi/core/hub/identity.ts:48`) — to reading the flag: `kind = process.env.BASECAMP_USER_FACING ? "agent" : "worker"`.

**Vocabulary migration (footgun — flag it in the migration).** The word `agent` flips meaning: today `role="agent"` is the *spawned* node and `role="session"` is the top-level one; under `kind`, `agent` is the *top-level/user-facing* node and `worker` is the spawned one. The row remap is `session → agent`, `agent → worker`.

## 5. Facets — what every node knows

| Facet | Source | Today |
|---|---|---|
| `repo` | `BASECAMP_REPO` — canonical `<org>/<name>`; **org rides inside it**, no separate column | set (`runtime.ts:70`), unread by identity |
| `worktree` | `BASECAMP_WORKTREE_LABEL` (empty when none) | on the env chain, dropped at register |
| `workstream` | join to `workstream_agents` (`workstream_id, repo, worktree_label, status`); **many-to-many** — a node may join several | side table, never joined to the roster |
| `is_workstream_agent` | **derived**: `EXISTS` a `workstream_agents` row for this node | encoded only in vestigial `product_role` |
| `parent` (who-spawned) | `parent_id` — `null` ⇒ human-spawned | **already present** |

`workstream` stays a **join, not a denormalized column** — membership is additive and repo-neutral (a workstream can span repos; [async-agents.md](./async-agents.md) and the workstreams model), so a single column can't hold it. `repo` and `worktree` are single-valued per node and become plain columns fed from env vars that already exist — the cheapest, highest-leverage part of this pass.

## 6. `product_role` & #244 — delete the seam, reberth the signal

Delete the whole seam: `pi/core/agent-role.ts` (provider registry + `resolveAgentRoleOverride` + `resetAgentRoleForTesting`), the `product_role` column, its tier-1 read in `identity.ts:71`, the sole registrant at `pi/workstreams/start.ts:255`, and the associated tests. #244's two consumers:

1. **Daemon identity display label** → gone. The roster shows `kind` + facets instead; there is no `"workstream_agent"` label.
2. **Worktree reuse on handoff** — the substantive one #244 parked, now answered by the **assignment model** (§6.1) rather than a role label. `shouldReuseActiveWorktreeForHandoff(agentRole, activeWorktree)` (`pi/tasks/workflows/handoff/index.ts:235`) today returns `agentRole === "workstream_agent" && activeWorktree !== null`, called with `resolveAgentRoleOverride()` (`:261`). Replace the role-label read with the agent's real **assignment state**: a workstream-assigned agent reuses its assigned worktree on handoff; a non-assigned agent gets the worktree flow as today. Handoff itself never warns — the launch-time guards (immutable assignment, no double-live-instance) live in §6.1.

This diverges from #244's plain deletion *and* from its "no distinction" thesis: the workstream distinction is real and kept — but it lives in `workstream_agents`, not a free-text label only one launcher ever set.

### 6.1 Assignment model & the launch guard

`--workstream` is kept **as-is**: it **assigns** an agent to a workstream at its initial launch, and the agent operates in that workstream's worktree. The assignment is a durable property of the agent — workstreams stay multi-agent/additive (one workstream holds many agents; AGENTS.md), but each *agent* carries one.

Two protections, both at the **pi launch / register handshake** — never in normal operation:

- **Set-once assignment.** An agent's workstream membership (`workstream_agents`, §5) is written once at its first `--workstream` launch and is **immutable** — re-launch/re-registration must **not re-home it** to another workstream. One agent carries one membership; the additive model already "never overwrites" (AGENTS.md), so this is consistent with it. The `agents`-row upsert updates mutable identity columns but never touches the membership.
- **No double-live-instance.** Launching an agent whose id **already holds a live connection** in the daemon registry warns/fails at register — you don't run one agent twice. A persisted-but-idle row with no live connection is a normal reconnect / re-task target, not a conflict.

Everything else is silent and normal: a first launch, a brand-new agent's assignment, and a same-session reconnect/reload (which upserts the same row) never warn.

## 7. Dropping mutative & its guards

Remove `run_kind` (`mutative | named-read-only | ad-hoc`, `pi/core/swarm/agents/types.ts:42`), `MUTATIVE_AGENT_NAME` (`types.ts:28`), the persona-driven `--read-only` gating, the in-process run guard (mutative-runs-solo), and the mutation-lease direction ([async-agents.md](./async-agents.md) §7.4 — Phase 3, never fully shipped). This is pre-mesh safety scaffolding; and because the `worker` *persona* was special **only** by being the mutative one, dropping the concept also frees the name for `kind = worker`.

**Consequence (resolved).** Nothing then serializes concurrent writers to a shared worktree. **For now workers share** the dispatcher's assigned worktree — concurrent mutating writes are the dispatching agent's concern (don't fan out mutating workers in parallel on one tree). **Isolation — 1 worker = 1 worktree — is the planned next pass** (§14), which removes the shared-tree coordination burden entirely.

## 8. Lifecycle & expiry

A node **joins** (`register` → `upsert_agent`, `app.py:151`), goes **idle** (WS disconnect → `schedule_disconnect_reaper`, `app.py:334`; the row persists), and eventually **expires**.

Expiry is **soft**, a **single global TTL**, tracked **per-row** off `last_seen_at`: on expiry the row is marked and **filtered out of the live roster / `list_agents`**, but **retained** for history. Any activity (reconnect, re-task, telemetry) resets it. This finally cashes the TTL that [async-agents.md](./async-agents.md) §6.5/§10 deferred; a hard-delete sweep remains a later follow-up. One TTL for all kinds (workers are the bulk of accumulation, but a uniform TTL is simpler and sufficient).

## 9. How it connects — the three overlays (recap)

Identity feeds all three, and only the first changes in this pass:

1. **Physical** — one WebSocket per node; `register` asserts identity; the daemon upserts a durable row keyed by `node_id` (the socket is ephemeral, the row is not).
2. **Tree (logical)** — `parent_id` / `sibling_group` / `depth`; scopes `discovery` / `wait` / `cancel`. **Unchanged.**
3. **Mesh (flat)** — any handle → any handle; `message` / `ask`. **Unchanged.**

The scoping lenses (follow-up) filter overlay-3's roster by the facets from §5 — a read-side concern with no wire or ACL change.

## 10. Decisions & rejected alternatives

| Decision | Chosen | Rejected |
|---|---|---|
| Mesh boundary | **Open mesh + lenses** (view-side scoping) | *Repo/workstream deny-rules on contact* — walls the mesh the product deliberately opened. |
| `kind` foundation | **Explicit `BASECAMP_USER_FACING` flag** | *json-mode / `hasUI`* — a rendering proxy that misclassifies headless top-level runs. *Pure daemon-spawned inference* — implicit; the launcher already knows and can just say so. |
| `product_role` | **Delete + reberth** on workstream membership | *Plain-delete (#244 as written)* — loses the "is-ws-agent" signal. *Repurpose as a filter key* — vestigial, session-only, free-text. |
| Workstream assignment | **Set-once / immutable; guarded at pi launch** (keep `--workstream`) | *Mutate-on-re-launch* — silently re-homes an agent. *Launch-agnostic collapse (#244's thesis)* — drops the assignment the model depends on. *One-agent-per-workstream* — workstreams stay multi-agent/additive. |
| Column name | **`role` → `kind`** (values `agent|worker`) | *Keep `role`* — lower churn, but `role="agent"` reads oddly and the two-role collision only dissolves, it doesn't clarify. |
| Mutative guards | **Drop entirely** | *Keep* — pre-mesh cruft; blocks the `worker`-name reuse and adds serialization the new model doesn't want. |
| Expiry | **Soft, single TTL, row retained** | *Per-kind TTLs* — unneeded complexity. *Hard-delete* — loses observability history. |

## 11. Schema, frame & boundary impact

- **`agents` table** (`src/basecamp/hub/store/agents/schema.py:16-33`): **add** `repo`, `worktree_label`, `user_facing` (or derive `kind`), `expires_at`; **rename** `role` → `kind` (remap `session→agent`, `agent→worker`); **drop** `product_role`, `run_kind`. Additive columns follow the existing `ALTER TABLE` pattern; the rename + drops need a one-shot migration (SQLite: rebuild, or stop-writing + backfill).
- **`RegisterFrame`** (`pi/core/hub/protocol/register.ts:3-16` + the Python Pydantic mirror + JSON fixtures): **add** `repo`, `worktree_label`, `user_facing`; `role → kind`; **drop** `product_role`. This is a wire change → **bump `PROTOCOL_VERSION`** and move the three hand-maintained copies together.
- **`identity.ts`**: rewrite the `role`/`product_role` derivation (`:48`, `:65`, `:69-76`) into `kind` + facet reads (`BASECAMP_REPO` / `BASECAMP_WORKTREE_LABEL` / `BASECAMP_USER_FACING`); drop the `agent-role.ts` import.
- **`policy.py`: unchanged.** No new deny path. **`directory.py`** listing gains the facet columns in its projection and an optional `expires_at` filter.
- **Python child env** (`src/basecamp/hub/swarm/process.py`): workers simply lack `BASECAMP_USER_FACING`; the interactive launcher sets it.
- **Deletes**: `pi/core/agent-role.ts` + `pi/core/tests/agent-role.test.ts`; the `daemon-identity` / `plan-handoff-worktree` / `workstreams/start` tests repoint; `pi/workstreams/start.ts` drops the registrant.
- **Tool-surface note** (unchanged, but now legible): top-level `agent`s get `dispatch`/`list`/`wait`; `worker`s get `ask`/`message`/`cancel` (`pi/core/swarm/agents/surfaces.ts:52-69`). The `kind` rename makes that split self-documenting.

## 12. Open questions

- **(a) Keep a distinct `attended` (`hasUI`) boolean** separate from `kind`, or is `kind` enough for the dashboard's "human watching now" lens?
- **(b) The TTL value** — a concrete default, and a config knob vs. a constant.
- **(c) Row migration** — remap `role→kind` and drop `product_role`/`run_kind` in one shot at daemon start vs. lazily.
- **(d) Warn vs. hard-fail** on a double-live-instance launch (§6.1) — surface-and-continue, or block the launch outright.

## 13. Sequencing (green at every step)

1. **Facets in, no deletes.** Add `repo`/`worktree_label` to identity → `RegisterFrame` → row (additive; version bump); join `workstream_agents` for `is_workstream_agent`. Nothing reads them yet. Green.
2. **`kind` + `USER_FACING`.** Rename `role`→`kind`, derive from the flag, remap rows. Green.
3. **Execute #244.** Repoint handoff onto `is_workstream_agent`; delete `agent-role.ts` + `product_role` + the registrant + tests. Green.
4. **Drop mutative.** Remove `run_kind` + guards + `MUTATIVE_AGENT_NAME`; workers share the dispatcher's worktree (§7). Green.
5. **Soft expiry.** `expires_at` + roster filter + activity reset. Green.
6. **Doc-true** AGENTS.md (the identity/env sections) + this record.

## 14. Deferred — the next pass

**Worker worktree isolation (1 worker = 1 worktree).** This pass has workers **share** the dispatcher's worktree (§7). The next pass gives each dispatched worker its **own** worktree, removing the shared-tree write-coordination burden entirely. It likely **promotes the worktree to a per-worker value on the spawn spec / env** — the dispatcher or daemon mints a worktree per worker and sets that worker's `BASECAMP_WORKTREE_*`, rather than the worker inheriting the dispatcher's — so the `worktree` identity facet (§5) flips from *inherited* to *worker-owned*. Scoped and designed in that pass; it does not block this one.
