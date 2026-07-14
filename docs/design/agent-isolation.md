# Agent Isolation — Design

**Status:** PROPOSED · design-only, **not implemented**. Supersedes this doc's earlier container/`sandbox-exec` direction. · **Scope:** Re-enable *mutative* dispatched agents by giving each its own git worktree, confining writes to it (structured guard + bash-reviewer), and integrating the result up the tree by merge — with the human review gate at the worktree immediately off main (W0). No OS container. · **Extends:** [async-agents.md](./async-agents.md) (daemon spawn/teardown lifecycle) — and **reverses** its "shared worktree + mutation lease" choice (§2/§9.2/§7.4). · **Motivates:** [#252](https://github.com/btimothy-har/basecamp/issues/252), [#253](https://github.com/btimothy-har/basecamp/issues/253), [#254](https://github.com/btimothy-har/basecamp/issues/254).

---

## 1. Problem statement

Dispatched agents read *untrusted* content — the code under `/code-review`, arbitrary repos a scout is pointed at, PR diffs. A prompt-injection payload there can try to make an agent mutate the user's real repository. The interim response (this repo's current state) is a **uniform read-only toolset**: `getAgentToolAllowlist()` (`pi/core/swarm/agents/types.ts`) withholds `write`/`edit` from every dispatched agent, each is launched `--read-only`, and the primary session is the sole mutator (`worker` returns a change *proposal*, it does not edit).

That is safe but limiting: real work has to funnel through one mutator. We want **mutative agents back** — agents that edit, run tools, and hand real changes up — without exposing the user's checkout. The blocker has always been `bash`: on a shared filesystem a read-only *toolset* is defense-in-depth, not a wall (`echo x > /abs/path`, `sed -i`, `tee`, `cp` all escape it, and the static bash gate triages them to ALLOW).

The earlier version of this doc concluded the only real boundary for `bash` is an OS sandbox (container / `sandbox-exec` / namespaces) over a disposable repo copy, writing results back as a host-applied diff ("Option C"). **That direction is dropped.** §2 explains why, and the rest of the doc specifies what replaces it.

## 2. Decision — worktree confinement, not containers

"Do we need a container?" decomposes into two orthogonal axes:

- **Axis 1 — coherence + write-back:** mutative agents produce changes that land cleanly. Solved by a *worktree strategy* + git. No container.
- **Axis 2 — bash blast-radius:** an injected `rm -rf ~` / `echo > /abs/host/path` can't reach the host. Only an OS sandbox closes this.

Re-enabling mutative agents is entirely an Axis-1 problem; the container is a pure Axis-2 add-on. We take Axis 1 (per-agent worktrees) and **decline the container**, for three reasons:

1. **It fights the daemon.** Every agent depends on the `0600` daemon UDS for telemetry, `wait_for_agent`, `ask_agent`, and peer messaging (async-agents §5). A container must either **sever** that socket (losing the whole async-collaboration surface) or **bind-mount** it in (handing a possibly-injected agent a live capability to spawn/lease/message — `0600` is moot once mounted). Worktrees keep the agent an ordinary host process with its normal daemon connection.
2. **It's leaky anyway.** The agent still needs its model key + `gh`/git credentials *inside* the sandbox — the very secrets the boundary was meant to protect.
3. **It's outside the threat model.** async-agents §5.1 already declares same-user processes inside the trust boundary (UDS is local-user-only). A container defends against an actor the project already trusts, at real cost (per-agent startup latency, image upkeep, cross-platform parity).

The cost of declining it is explicit and accepted: **`bash` blast-radius stays uncontained** (see §6). We raise the bar with the bash-reviewer (§4.3) but do not claim a wall.

## 3. The model

### 3.1 One rule: write only your own active worktree

Every actor — the human-facing session *and* every dispatched agent — may make structured/`bash` writes **only within its own active worktree** (plus the session scratch dir and other registered allowed-roots). No active worktree ⇒ no repo writes. This single rule replaces the special-cased "protected checkout" apparatus:

- The **main checkout is nobody's worktree**, so it is never writable by anyone — *protected as a corollary*, with no dedicated machinery.
- Pre-handoff (a work-mode session sitting on main with no worktree yet) ⇒ "no write scope yet, activate one first."

`validateProtectedCheckout`'s special protected-root logic and the two-branch protected-checkout guard collapse into this one rule.

### 3.2 Per-agent worktrees + upward merge

A dispatched **mutative** agent is launched into **its own** locked worktree, branched from its parent's `HEAD`. It works there, **commits to its branch**, and stops — it *produces a branch*, it does not merge. The **parent** integrates that branch into the parent's own worktree by `git merge`, on review. Read-only agents (scouts, reviewers, `ask`) keep sharing the parent's checkout read-only (they need live WIP, and they don't write).

This is recursive — "parent" is whoever dispatched. The tree of the two human workflows converges here:

```
Path 1 (interactive):  main → plan-approved W0 → agent worktrees
Path 2 (copilot):      main → workstream W0     → agent worktrees

              main  (root; reached only via PR from W0)
                │
                W0  (human-facing worktree — the sole human gate)
              ╱  │  ╲
            W1  W2  W3   (agent worktrees; each merges up into its parent)
            │
            W1a … (depth-capped; parent integrates children autonomously)
```

Per-agent worktrees **dissolve the mutation lease**: the lease existed only to serialize writers on a *shared* tree (async-agents §7.4). Separate worktrees have no shared writer, so the lease and its deadlock-cycle detection (Phase 3) are unnecessary. `git worktree lock` here is a *liveness* guard (stop cleanup/migration from yanking a tree mid-run), not a mutation lease.

### 3.3 Trust model

**W0 — the worktree immediately off main — is the sole human review gate.** All sub-agent changes converge into it, and it reaches main only through the existing PR flow. Everything below W0 is one **autonomous** trust domain: agent-to-agent integration is *not* human-gated; the human reviews only the **aggregate** that lands in W0. The subtree is bounded by the depth cap (default 2), so it is shallow, not unbounded recursion.

"Only W0 is gated" splits the threat surface, and W0 covers exactly one half:

- **In-scope malicious content** (a sub-agent slips a backdoor into code it was legitimately editing, which merges up): caught **only** at W0. So the W0 review is **load-bearing** — the single failure mode of the whole model is a human blind-approving the W0→main diff.
- **Escape / exfiltration** (a sub-agent writes *outside* its worktree, or reads secrets and phones home): W0 review **structurally cannot** catch this — it never appears in W0's diff. The only defense is per-level worktree confinement + bash-reviewer, and with no human checkpoint below W0 there is no backstop if the bash-reviewer is evaded.

Both sit inside the same-user local-dev trust boundary (async-agents §5.1). This is a deliberate, bounded place to land — the design states it plainly rather than implying a wall.

## 4. Mechanics

### 4.1 Naming

Sub-agent worktrees and branches share one reserved namespace, disjoint from every human-facing name (`wt-<prefix>/<slug>`, `copilot/<slug>`, `<user-prefix>/…`):

- **Worktree label & branch (same string):** `agent-<id>/<name>` — e.g. `agent-3f9a2c/worker`.
- **Path:** `~/.worktrees/<org>/<repo>/agent-<id>/<name>/`.

`<id>` is a prefix of the dispatcher-minted `agent_id` UUID — available at provision time with **no dependency on daemon handle-derivation** — sized long enough that a label collision (which would fail `worktree add`) is implausible across concurrent agents. `<name>` is the agent type (`worker`, …), `adhoc` for ad-hoc agents. Id-first gives each agent its own `agent-<id>/` directory (whole-subtree teardown) and front-loads uniqueness. Reserve the `agent-` prefix — no user-prefix may produce `agent-*`. The branch **outlives** the worktree (§4.5): teardown removes the directory but keeps `agent-<id>/<name>` for the parent to merge, and the parent deletes the branch only after integrating.

### 4.2 Dispatch — the `readOnly` fork

Agent config gains one bit, `readOnly?: boolean`, **fail-closed (default `true`)**: omit it → today's safe read-only behavior; `worker` sets `readOnly: false`. The name aligns with the existing `--read-only` flag / `read-only.md` vocabulary; defaulting to the safe value if forgotten is the right failure mode, and it matches reality (scouts/reviewers/`ask` are read-only; `worker` is the exception).

- **read-only agent** ⇒ today's path verbatim: `cwd`=repo root, `--worktree-dir`=parent's worktree (shared), `--read-only`, read-only toolset.
- **mutative agent** ⇒ provision `agent-<id>/<name>` from the parent's `HEAD`, lock it; **spawn with `cwd`=that worktree** (the workstream pattern), so `runtime.initialize` auto-adopts it via `isLinkedWorktree` (protectedRoot=main, activeWorktree=Wn) — no `--worktree-dir` needed; **no** `--read-only`; `write`/`edit` added; bash-reviewer active. Repo identity stays canonical because `resolveGitInfo` derives `repoName` from the remote URL, not the cwd basename (this corrects the async-agents §6.6 rationale, which claimed cwd had to be the repo root for identity).

The daemon is **unchanged** — the spawn spec's `cwd`/argv travel opaquely (async-agents §6.2); `spawn_agent_process` executes them as-is.

### 4.3 Confinement — the guard + symmetric bash review

Both layers read one shared **`allowed_dirs`** primitive built into core (`allowedWriteDirsFrom` / `listAllowedWriteDirs` in `pi/core/project/workspace/state.ts`): the current write scope = **active worktree ∪ session scratch ∪ allowed-roots**; main is never in it. Because each pi process has its own workspace state, an agent process resolves this to its own `Wn` and the human session to `W0` with no branching. Both are applied to agents *and* the user's own `!bash`, held to one rule (§3.1):

- **Structured `write`/`edit`:** the workspace guard blocks any mutation whose resolved path is outside `allowed_dirs` — closing the absolute-path escape (e.g. writing into a sibling worktree by absolute path). *(Implemented.)*
- **`bash` (agent bash and user `!bash` alike):** routed through the bash-reviewer against the same `allowed_dirs`, which parses write-targets (redirects, `sed -i`, `tee`) a structured path check can't see. This enforces the "nobody edits main" contract *symmetrically*. `!git status` passes; `!echo x > main/f` is refused. *(Later increment — the primitive is ready.)*

This is bar-raising, not a wall (§6): a review can be evaded by dynamic paths, symlinks, or indirection. It belongs to the same defense-in-depth tier as the read-only toolset.

### 4.4 Commit contract

A mutative agent's branch is its only deliverable, so it must not finish dirty. A **mutative-only completion guard** — the same interception shape as the runner's empty-result retry (async-agents §6.3.1) — checks `git status --porcelain` in the agent's worktree at run completion; if dirty, it steers the agent back to commit and re-finish. **No auto-commit override** — the agent commits its own work. Bound the reminders (≈2); still dirty after that ⇒ fail the run (uncommitted work is honestly discarded at teardown, not silently rescued).

### 4.5 Integration & teardown

Integration is a **judgment** step (review the diff, resolve conflicts), so it is plain `bash` + `git` in the trusted parent — **no integration tool**. The branch name is deterministic (`agent-<id>/<name>`) and the parent already holds `<id>` from dispatch/`wait_for_agent`, so it merges without a lookup.

Worktree and branch have **decoupled lifetimes**, and worktree teardown is **system-owned** (the bash-reviewer blocks every `git worktree` subcommand). The **daemon reaper removes the worktree when the agent's run exits** — `reclaim_agent_worktree` (`src/basecamp/hub/swarm/process.py`), keyed by the spawn spec's `owned_worktree` (which the dispatcher sets for mutative agents) — the symmetric bookend to provision-at-dispatch, so worktrees never leak. The committed branch persists as the deliverable; the parent `git merge`s it and then `git branch -d`s it (both allowed — neither is a `git worktree` command, and the branch is free to delete once the reaper removed its worktree). A **session-start merged-worktree sweep** (`pi/core/git/worktrees/sweep.ts`) is the backstop for the rare reaper miss (e.g. a daemon crash mid-reap): it removes `agent-*` worktrees whose branch is already merged into a non-agent branch. Residual: a *finished-but-never-merged* branch left undeleted lingers as a cheap ref until a later pass.

### 4.6 W0 provisioning — the leaned-on contract

W0 branches from the main checkout's **current `HEAD`** (respects a user intentionally on a feature branch; matches Claude Code's `baseRef: head`). The **on-default-branch gate is dropped.** The **clean-assertion is kept** — but reframed as the *enforcement of a load-bearing contract*: because branch-from-HEAD depends on main being clean, and we enforce that on agents, we must enforce it on the user too, or it is silent WIP-stranding.

Because the check is load-bearing at exactly one instant (W0 creation), lift it out of the git layer (where it throws *at* creation ⇒ teardown of in-flight handoff state) up into the runtime as a **pre-flight gate + proactive alert**:

- **Pre-flight gate** at the decision points — plan approval (`pi/tasks/workflows/handoff`) and `launch_workstream` (`pi/workstreams/provision.ts`) — asserts main clean (and target label free) **before any provisioning** (worktree, pane, up-to-3-min setup hook). Dirty ⇒ abort with guidance, **zero teardown**.
- **Ambient alert** — check main cleanliness at `session_start` and on entering planning/work mode, surfaced in the UI (`pi/core/ui/header.ts`) so the user commits/stashes *while still discussing*, before ever reaching the gate. No per-turn polling.

`validateProtectedCheckout`'s clean-assertion stays as the innermost belt, but with the pre-flight in front it should almost never fire.

## 5. What this drops or reverses

- **Container / `sandbox-exec` / Option C disposable-copy + host-applied diff** — dropped (§2).
- **async-agents §2 non-goal "No worktree-per-agent + merge" and §9.2's rejection of it** — reversed; per-agent worktrees are now the model.
- **Mutation lease + deadlock detection (§7.4, Phase 3)** — dissolved by per-agent worktrees; `git worktree lock` is a liveness guard only.
- **`validateProtectedCheckout` on-default-branch gate + in-creation clean-throw** — the branch gate is removed; the clean-check relocates to a pre-flight runtime gate.
- **The special "protected checkout" guard branches** — collapsed into the one uniform worktree rule; the generic `workspace/guards.ts` grab-bag becomes a simple worktree-confinement module.
- **`unsafe-edit`** (`unsafe-edit.ts`, `buildUnsafeEditGuidance`, the `unsafeEdit` state) — retired. It existed only to let the human-facing session edit the *protected checkout directly*; under the uniform rule main is nobody's worktree and never writable, so the escape hatch contradicts the contract now being enforced.

## 6. Residual risk (stated, not hidden)

- **Uncontained `bash` below W0.** The bash-reviewer raises the bar but is a review, not enforcement; a determined injection can still escape a worktree. There is no human backstop below W0 for escape/exfiltration (§3.3).
- **External-editor drift on main.** Real-time edits to the main checkout between transitions aren't interceptable (short of absurd file-watching). This is caught at the next point we depend on the contract — the W0-creation pre-flight — which is the only instant it is load-bearing.

Both are accepted consequences of operating inside the same-user local trust boundary.

## 7. Component placement

The daemon (`src/basecamp/hub/`) needs **no change** — this is a TS-side feature. Everything worktree-semantic lives in the dispatching pi process.

| Design element | Home |
|---|---|
| `remove` / `lock` / `unlock` / branch-from-ref primitives | `pi/core/git/worktrees/crud.ts` (224 lines — watch the 350 cap; split to `lifecycle.ts` if it grows) |
| Worktree reaper (primary teardown, on run exit) | `reclaim_agent_worktree` in `src/basecamp/hub/swarm/process.py`, keyed by the spawn spec's `owned_worktree` — **implemented** |
| Merged-worktree sweep (session-start backstop) | `pi/core/git/worktrees/sweep.ts`, wired beside the legacy migration — **implemented** |
| Worktree-confinement guard (dismantle the grab-bag → simple confinement) | stays in `pi/core/project/workspace/` (reframed from `guards.ts`); data-cohesion is with `WorkspaceState`, not the stateless git layer |
| Retire `unsafe-edit.ts` + `buildUnsafeEditGuidance` + `unsafeEdit` state | `pi/core/project/workspace/`, `pi/system-prompt/context-builders.ts` |
| Retire `validateProtectedCheckout` special logic | `pi/core/git/worktrees/crud.ts` |
| `readOnly` agent-config bit | `pi/core/swarm/agents/discovery.ts`; `worker` in `pi/core/swarm/agents/builtin/worker.md` |
| Dispatch fork (mutative → provision + no `--read-only` + `write`/`edit`) | `pi/core/swarm/agents/executor.ts` + `launch.ts` |
| Completion guard (commit-before-finish) | agent-side hook in `pi/core/swarm/agents/` (TS, mutative-only) — *not* the Python runner |
| Symmetric bash-reviewer against authorized-dirs | `pi/bash-reviewer/` (review/triage) consuming write-scope from `#core/project/workspace` state |
| Pre-flight gate + shared "is main dirty?" helper | gate calls in `pi/tasks/workflows/handoff` & `pi/workstreams/provision.ts`; helper once in `pi/core/git/` |
| Ambient dirty-main alert | `pi/core/ui/header.ts` + a `session_start`/mode-change check |

Layering call: `pi/core/git/worktrees/` stays **stateless primitives** (git verbs, no pi hooks, no session state — testable in isolation). Worktree *confinement* is session-runtime enforcement whose data-cohesion is with `WorkspaceState` (it reads active-worktree / effective-cwd / allowed-roots and writes no git), so it stays in `workspace/` even though its *subject* is worktrees. The guard is already DI-shaped (`getState`/`getAllowedRoots` providers), so this is a rename + simplification, not a move.

Open placement seam: the bash-reviewer must read the current write scope (active worktree) from workspace state — a `#core/project/workspace` import from the `bash-reviewer` domain, boundary-checked.

## 8. Prototype slice

Prove provision → confine → commit → merge → teardown end-to-end with the smallest cut: `crud.ts` primitives (1) + `readOnly` fork (4.2) + the uniform guard (4.3, structured only) + one mutative `worker` that commits a branch which the human-facing agent merges into W0 **by hand**. Defer to follow-ups: the symmetric bash-reviewer authorized-dirs pass, the completion guard, and the pre-flight/ambient alert. (The merged-worktree sweep is implemented — §4.5.)

## 9. Prior art — Claude Code worktrees

Claude Code's framing is load-bearing here: *"Worktrees handle file isolation."* It never claims bash containment — edits in one session simply don't touch another's files. That confirms the split this doc rests on: a worktree is where edits land and how they merge back (Axis 1), **not** a security sandbox for what bash can reach (Axis 2). Its mechanics are the template for the pieces above: `isolation: worktree` auto-removed when a subagent finishes clean; `worktree.baseRef: "head"` to carry in-progress work (our §4.6); `git worktree lock` held while the agent runs (our liveness guard); a `cleanupPeriodDays` sweep (our orphan sweep, §4.5).
