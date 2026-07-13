# Agent Isolation — Design

**Status:** PROPOSED · design-only, **not implemented**. Captures the direction for containing what a dispatched agent's `bash` can do, and for safely re-enabling *mutative* agents on top of that containment. · **Scope:** Run each dispatched agent inside an OS-level sandbox (container / `sandbox-exec` / namespaces) whose filesystem view is a disposable copy of the repo; write results back to the host as a diff the trusted host applies. · **Extends:** [async-agents.md](./async-agents.md) (the daemon + spawn/teardown lifecycle), [agent-roles-identities.md](./agent-roles-identities.md) (which **dropped** the mutative/`run_kind` guards this doc's interim posture replaces). · **Motivates:** [#252](https://github.com/btimothy-har/basecamp/issues/252) (reviewers fed untrusted content), [#253](https://github.com/btimothy-har/basecamp/issues/253) (no-worktree bash reaches the main checkout), [#254](https://github.com/btimothy-har/basecamp/issues/254).

---

## 1. Problem statement

Dispatched agents read *untrusted* content — the code under `/code-review`, arbitrary repos a scout is pointed at, PR diffs. A prompt-injection payload in that content can try to make the agent mutate the user's real repository. The identity/role rework ([#244](https://github.com/btimothy-har/basecamp/issues/244), [agent-roles-identities.md](./agent-roles-identities.md)) removed the per-persona guards, and the interim response (this repo's current state) is a **read-only toolset**: `getAgentToolAllowlist()` (`pi/core/swarm/agents/types.ts`) withholds `write`/`edit` from every dispatched agent, each is launched with `--read-only`, and the primary session is the sole mutator.

That closes the **structured** mutation path — but not `bash`, and `bash` cannot be closed on a shared filesystem:

- **The static bash gate does not catch plain writes.** `pi/bash-reviewer/triage/` classifies `rm -rf`, `sudo`, `dd`, and git/gh mutations, but `echo x > /abs/path`, `sed -i`, `tee`, and `cp` all triage to **ALLOW** and run unguarded. `git-mutation` is even auto-*approved* for a no-UI subagent (`SUBAGENT_APPROVE_CATEGORIES`, `pi/bash-reviewer/review.ts`).
- **A worktree is not a sandbox.** The workspace guard (`pi/core/project/workspace/guards.ts`) rewrites only *relative* bash cwd into the active worktree; an absolute-path write (`echo x > /Users/.../main-checkout/f`) escapes it, and its bash branch early-returns entirely when no worktree is active (#253). The worktree shares the host filesystem, user, and permissions.

**Conclusion:** on a shared filesystem, read-only-by-toolset is defense-in-depth, not a wall. The only real boundary for `bash` is OS-level isolation. That same boundary is what would let us **bring back mutative agents** without exposing the main checkout — the reason to invest in it.

## 2. Direction — disposable sandbox, host-applied write-back

Run each dispatched agent inside an OS sandbox whose only writable filesystem is a **disposable copy of the repo**. Inside the sandbox the agent may edit and `bash` freely; nothing it does reaches the host except a **diff the host chooses to apply**.

```
DISPATCH ─ daemon spawns agent INSIDE a sandbox
   │        (mount ns / container / sandbox-exec)
   ▼
  sandbox fs:  /workspace = disposable repo copy   (host main checkout NOT in the namespace)
   │
   ├─ agent edits + bash freely; absolute paths to the host checkout do not exist here
   │
   ▼
TEARDOWN ─ daemon extracts `git diff` → writes `<tmp>/<agent_id>.diff`
   │
   ▼
HOST ─ trusted host validates the diff (scope-checks touched paths) and `git apply`s it,
        or discards it. The sandbox is destroyed.
```

Two agent classes ride on the same mechanism:

- **Read-only agents** (scouts, reviewers, `ask`) — no write-back; the sandbox is pure blast-radius containment. `bash` genuinely cannot touch the host checkout because that path is not in the sandbox's namespace.
- **Mutative agents** (re-enabled) — the diff is the deliverable; the host is the gate on what actually lands.

## 3. Write-back — Option C (host-applied diff artifact)

Three write-back mechanisms were considered:

| | Mechanism | Isolation | Verdict |
|---|---|---|---|
| A | Bind-mount a host worktree into the sandbox | Weak — must also expose `.git`, which the sandbox can then corrupt | rejected |
| B | Clone in, `git fetch` out (host objects read-only) | Strong; clean git audit trail | viable fallback |
| **C** | **Agent works on a throwaway copy; daemon emits `git diff`; trusted host validates + `git apply`s** | **Strong; host is the gate on what lands** | **chosen** |

**Option C** keeps the security property through write-back: the sandbox never writes host state directly. On teardown the daemon **artifacts the result back as a `.diff` file in tmp** (`<tmp>/<agent_id>.diff`); the host scope-checks that the diff touches only expected paths and applies it (or rejects it). This is the natural extension of the read-only posture — you already don't trust what the agent's `bash` did, so you validate its output before letting it land.

## 4. Daemon lifecycle hooks

The daemon already owns agent spawn and teardown (see [async-agents.md](./async-agents.md)); the map below is where sandboxing wires in. Line numbers are indicative.

- **Spawn** — `spawn_agent_process` (`src/basecamp/hub/swarm/process.py`, the single `asyncio.create_subprocess_exec(*argv, cwd=…)`). Wrap `argv` in the sandbox launcher (`docker run …` / `sandbox-exec …` / `bwrap …`) and provision the disposable repo copy here. `agent_id`, `run_id`, `spec.cwd`, and `spec.argv` are all in hand at the call site.
- **Teardown** — the reaper's `finally` (`process.py`, `reap_agent_process`) fires exactly once per run on *any* child exit including crash. Extract the diff and destroy the sandbox here.
- **Restart reconciliation** — `reconcile_orphaned_runs` (`process.py`, wired at daemon startup) is today the only orphan sweep, and it reclaims **processes + DB rows only**. It must be extended to reclaim orphaned sandboxes and stale `.diff` artifacts.
- **Lifecycle keys to the *agent*, not the run.** Agent rows are reused across retasks (`prepare_dispatch` existing-agent branch); a sandbox that outlives a single run must be agent-scoped, while the reaper fires per-run. Be deliberate about this mismatch.

Worktree CRUD (`pi/core/git/worktrees/crud.ts`) has create/attach/list/move but **no remove primitive** — any disposable-copy scheme adds its own teardown; it does not reuse the plan-approval worktree machinery.

## 5. Costs & open questions

- **Runtime dependency + portability.** A container runtime (Docker/Podman) or an OS sandbox per platform (macOS `sandbox-exec` / Apple `container`; Linux `bwrap` / namespaces). Cross-platform parity is the largest tax.
- **Per-agent latency.** Current spawn is milliseconds; a container is seconds plus image/copy setup. Read-only scouts are dispatched liberally — startup cost matters.
- **Secrets into the sandbox.** The agent still needs its model API key and `gh`/git credentials *inside* the sandbox, which partially reopens the boundary. Scoping/rotating those is an open question.
- **Repo state in.** Bind-mount (fast, but couples to host paths) vs. clone/copy (isolated, slower for large repos) vs. a shared read-only object store with a copy-on-write working tree.
- **Diff validation policy.** What path scope is "expected", and what happens on a diff that touches outside it — reject, or surface for human review.

## 6. Interim posture (shipped)

Until the sandbox exists, the boundary is the **read-only toolset** — every dispatched agent gets `read/bash/grep/find/ls` (no `write`/`edit`) plus `--read-only`, the primary session is the sole mutator, and the `worker` agent returns a change proposal rather than editing (`pi/core/swarm/agents/types.ts`, `executor.ts`, `builtin/worker.md`). The workspace guard independently hard-blocks structured writes to the protected main checkout even with no active worktree (`pi/core/project/workspace/guards.ts`; pinned end-to-end by `pi/core/swarm/agents/tests/launch-workspace.test.ts` for #254). The residual `bash` write path is the accepted gap this document exists to eventually close.

## 7. Prior art — Claude Code worktrees (the file-isolation layer)

Claude Code ([docs](https://code.claude.com/docs/en/worktrees)) ships a mature per-session and **per-subagent** worktree model. Its own framing is the load-bearing point: *"Worktrees handle file isolation."* It never claims bash containment — edits in one session simply don't touch another's files. That **confirms this document's thesis**: a worktree is not a security sandbox; it is where edits land and how they merge back. The two concerns are separate layers:

- **Worktree = file-isolation + write-back.** One agent's edits don't collide with another's; the worktree is a branch, so "write-back" is an ordinary merge (simpler than §3's diff-artifact, which the container case needs because its filesystem is separate).
- **Container / OS-sandbox = bash-isolation.** What bash can *reach* (§2). Absolute-path writes and `rm -rf ~` are only contained here, never by a worktree.

They compose: a mutative agent runs in a **worktree inside a container** — the container bounds bash, the worktree bounds edits and carries the branch back.

Claude Code's mechanics also refute two objections previously raised against per-agent ephemeral worktrees here, and are the template if/when basecamp re-enables mutative agents:

- **`isolation: worktree`** subagent frontmatter → a temporary worktree **auto-removed when the subagent finishes without changes** (issue #253's deferred "1 agent = 1 worktree" pass, proven).
- **`worktree.baseRef: "head"`** branches from local `HEAD` so the worktree **carries in-progress/unpushed work** — the answer to "a fresh worktree misses the parent's WIP", which reviewers/scouts need.
- **Teardown lifecycle**: clean → auto-remove; dirty → keep/prompt; a `cleanupPeriodDays` sweep reaps stale clean worktrees; **`git worktree lock` is held while the agent runs** so cleanup can't race it. (basecamp's `pi/core/git/worktrees/crud.ts` still has no remove primitive — this is the model to build.)
- **`.worktreeinclude`** (gitignore syntax) copies gitignored config (`.env`) into the fresh checkout — the gap a bare `git worktree add` leaves.

**Bearing on the current (read-only) posture:** with every dispatched agent read-only, per-agent worktrees buy little *now* — read-only agents create no edit-collisions, and a worktree wouldn't close the bash path anyway. So the file-isolation layer is deferred to the mutative-agent work, where it pairs with the container's bash-isolation layer above; it is not a substitute for it.
