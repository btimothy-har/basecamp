# Copilot on Claude Code — Port Proposal

**Status:** PROPOSAL (2026-07) · **Scope:** how the basecamp *repo copilot* (the `--copilot` posture + workstreams + repo memory) lands on Claude Code, native-first · **Builds on:** [claude-code-compatibility](./claude-code-compatibility.md), [`claude/README.md`](../../claude/README.md), [transcript-ingestion](./transcript-ingestion.md), [async-agents](./async-agents.md) · **Delivery:** the `claude/` plugin + the kept Claude hub daemon

This proposal turns the "🟡 dropped / optional Tier-2" copilot row of [claude-code-compatibility](./claude-code-compatibility.md) §4 into a concrete port. It examines the full copilot surface as built on Pi, then maps each mechanism to the **most native Claude Code feature that fits**, falling to the (already-kept) hub daemon only for the irreducible cross-session coordination core. Nothing here is built yet; this is the design record to argue over before code.

> **Revision (2026-07).** Incorporates review decisions that reshape the data model: memory stays **Logseq as a shared location**, with each **workstream writing its own dossier** (not copilot-only); staging uses **native, ephemeral worktrees** with the instructions **bundled into the skill**, and the model **anchors on staging** — a workstream can span **multiple worktrees**, so the durable git anchor is the **branch**, not the worktree; workstream records are a **net-new schema in the separate Claude daemon** (not a port of the Pi tables); and **status** resolves to *read the workstream's own dossier*, with a **daemon-forked ephemeral session** as the live escalation. §2–§9 reflect these; §1 is the unchanged Pi-surface recap.

---

## 1. What "copilot" is today

Copilot is a **locked, launch-only session posture** (`pi --copilot`) whose job is to be a repo's coordination partner: orient to the user's focus, reconcile signals (repo memory, GitHub, git, issue trackers), make the work *choice-set* legible (active / waiting / blocked / stale / proposed / not-now), **shape execution-ready workstreams**, and **keep durable repo memory current**. Its defining discipline is what it does *not* do: it **stages** work, it does not implement in-session; it **hands off** a workstream to an independent session, it does not supervise, drive, or manage that session.

It is assembled from five mechanisms. This is the surface we are porting:

| # | Mechanism | Pi implementation (verified) |
|---|---|---|
| 1 | **Posture / loop** | `modes/copilot.md` fully *replaces* the system prompt (no working-style layer); the copilot loop is the persona. |
| 2 | **Mode lock** | `--copilot` (boolean flag) forces `agentMode = "copilot"` at every `session_start`; immutable (`cycleAgentMode` is a no-op in copilot, and copilot is excluded from the cycle set); hides `plan()` via two layers (a `tool_call` guard + a capabilities-index filter). Takes precedence over `--workstream`. |
| 3 | **Workstream records** | Durable records in the Pi swarm daemon's SQLite (`workstreams` + `workstream_versions` + `workstream_agents`). Identity = internal `ws_<uuid>` + globally-unique three-word `slug`. Content (`label`/`brief`/`constraints`) is versioned (append-only). Status `open`/`closed`. Points at a dossier via `source_dossier_path`. Tools (top-level session only): `create_workstream`, `edit_workstream`, `launch_workstream`, `list_workstreams`, `set_workstream_status`. |
| 4 | **Execution staging** | `launch_workstream` provisions the `copilot/<slug>` git worktree (branch `<user-prefix>/<slug>`, e.g. `bt/…`) and best-effort opens a **Herdr** tmux pane on it. It does *not* start an agent — the user runs `pi --workstream` in the pane, which (on a genuinely fresh session only) attaches the session as an additive `workstream_agents` row and injects the current brief as a synthetic user message. |
| 5 | **Repo memory (Logseq)** | Two markdown page types under one graph dir: a repo **cockpit** `repo__<org>__<repo>.md` and per-work **dossiers** `work__<org>__<repo>__<slug>.md`. Copilot is the **sole writer** (via `write`/`edit`); read is lazy (the prompt names the paths, the agent reads them). |

Cross-session reach (part of #4/#5): copilot discovers a launched workstream's agent **handle** from the joined agent rows of `list_workstreams`, then uses `ask_agent` (a *fork of the target's transcript* — non-interrupting) or `message_agent` (one-way push into the live session) to pull a current-state summary. Copilot has *contact-only* authority over that session — the daemon's policy layer denies list/wait/cancel/retask across session roots; copilot.md restates the wall.

### Two daemons — the single most important fact

There are **two** hub daemons in the repo, and the port hinges on the distinction:

| | **Pi swarm daemon** | **Claude session daemon** (`hub/claude/`) |
|---|---|---|
| CLI | `basecamp hub --legacy` | `basecamp hub` (**the default**) |
| Transport | WebSocket (`/ws`) + read-only HTTP GET, over UDS | HTTP-over-UDS only (short-lived POST/GET; **no** WebSocket) |
| DB | `~/.pi/basecamp/swarm/daemon.db` | `~/.pi/basecamp/claude/daemon.db` |
| Protocol gate | `PROTOCOL_VERSION = 23` | `CLAUDE_PROTOCOL_VERSION = 3` |
| Owns workstreams? | **Yes** (all of #3/#4/#5's coordination) | **No** — `sessions` + `episodes` + `transcript_nodes` only |

The Claude daemon is the go-forward one: a clean-room, "promotable" rebuild that depends on nothing Pi. It already ships the session lifecycle (register/end + episodes) and **already ingests every Claude Code session's transcript** — main thread *and* every subagent sidecar, keyed by node `uuid`, tagged with `repo` / `worktree_label` / `session_id` ([transcript-ingestion](./transcript-ingestion.md)). It has **zero** workstream, agent-registry, dispatch, or messaging surface today. That gap, and that already-built transcript store, together shape the whole port.

---

## 2. The porting principle

[claude-code-compatibility](./claude-code-compatibility.md) already set the rule: **static assets → native plugin components; only computed-per-session context → the MCP server; already-native → dropped.** This proposal sharpens it for copilot with one addition:

> For each copilot mechanism, take the **most native Claude Code feature that fits**. Fall to the **kept Claude daemon (via MCP tools)** only for state that is *irreducibly cross-session and durable* — a record that must outlive one session and be queried from another. Everything a git branch or a shared markdown file can hold, let it hold.

Applying it decomposes the monolithic "copilot mode" into five layers landing in **three** homes. Three of the five are fully native; only the workstream *record* needs the daemon:

| Layer | Native-first port | Home | Native? |
|---|---|---|---|
| **Posture** (loop/persona, #1+#2) | a `copilot` **skill** (the loop, verbatim-adapted), entered via `/basecamp:copilot`. Drop the mode-lock and the `plan()` guard. | native skill | ✅ fully native |
| **Memory** (#5) | markdown **files in a shared Logseq graph** (native `Write`/`Edit`) + one MCP **read resource**. Writes decentralize: copilot owns the repo **cockpit**; each workstream owns and writes **its own dossier**. | native + 1 MCP resource | ✅ native |
| **Staging** (#4) | native, **ephemeral** worktrees (`claude -w` / `EnterWorktree`) with the how-to **bundled in the skill**; the **branch** is the retained anchor; a SessionStart hook injects the brief when a session opens on a workstream branch. Drop Herdr. | native worktree + existing hook | ✅ native |
| **Records** (#3) | a **net-new schema in the Claude daemon** + MCP tools. The record anchors a workstream to its **branch(es)** and **dossier**; the dossier stays the human-facing narrative. | daemon + MCP tools | ⚠️ irreducible daemon core |
| **Status** (cross-session reach) | **read the workstream's own dossier** (it self-reports into shared Logseq). For a live answer the dossier lacks, the **hub forks an ephemeral `claude -p`** continued from that session's transcript — non-interrupting. Drop `message_agent`. | native file read + daemon fork | ✅ mostly native |

### 2.1 The data model: anchor on staging, not on worktrees

The reshape turns one durable artifact (Pi's daemon-owned worktree-bearing record) into three, each in its natural store:

- **The record** (staging) — the durable coordination fact, in the **Claude daemon**: identity, brief, status, and pointers to the branch(es) and dossier. This is the anchor.
- **The branch(es)** (git) — the durable code anchor. Worktrees are **ephemeral** compute (native `.claude/worktrees/`, auto-cleaned); a workstream may spin up several over its life, on one or more branches, and tear them down. Git retains the branch; the record retains the branch *name(s)*. **No worktree path is persisted.**
- **The dossier** (shared Logseq) — the durable narrative anchor, **written by the workstream itself**: priority, decisions, blockers, done-signal.

A workstream is therefore **1‑record → N‑branches → N‑ephemeral‑worktrees → 1‑dossier**, and "which repos/branches touched" derives from the record's branch and session rows. Copilot *stages* (mints the record, names the branch, seeds the dossier); execution is disposable and reconstructable from those three anchors.

---

## 3. Layer-by-layer mapping

### 3.1 Posture → a `copilot` skill (fully native)

The copilot loop — orient, reconcile signals, make the choice-set legible, shape workstreams, curate the cockpit — is prose guidance. It ports to a native **skill** (`skills/copilot/SKILL.md`), the same shape as the landed `planning`, `gather`, and `pr` skills. `modes/copilot.md` becomes the skill body almost verbatim; edits strip Pi-runtime jargon (per the compat doc's model-facing-content principle), re-point tool references at the new MCP tools, and — new — **bundle the staging how-to** (§3.3) so staging needs no dedicated launch tool.

Entry is `/basecamp:copilot` (skills auto-namespace `plugin:name` and can auto-surface by description). It is deliberately *per-session*, not global.

**Dropped, safely:** the mode-lock (Claude Code has no lockable mode; copilot is a posture you enter, and the "stage, don't implement" discipline is skill prose) and the `plan()` hide (native plan mode is fine; copilot just won't lean on it). Both align with the compat doc's "don't port enforced modes."

**Alternative — an output style.** Plugins can ship output styles that replace the prompt wholesale (`force-for-plugin: true` + `keep-coding-instructions: false` = Pi's exact "mode replaces the prompt"). Declined as default: `force-for-plugin` is **plugin-wide, not per-session**, so it can't be launch-conditional the way `--copilot` was. Kept as an opt-in for a copilot-dedicated install.

### 3.2 Memory → shared Logseq, decentralized writes (fully native)

Logseq stays — it is just markdown, and it **becomes a shared location**: one graph, visible across repos and sessions, the coordination substrate both copilot and workstreams read and write. This is the most native layer (plain `Write`/`Edit` on `.md` files) and it gains one deliberate change from Pi:

- **Writes decentralize.** Copilot owns the **repo cockpit** (`repo__<org>__<repo>`) — repo-level orientation, priority shifts, the choice-set, cross-workstream decisions. **Each workstream owns and writes its own dossier** (`work__<org>__<repo>__<slug>`) — its progress, decisions, blockers, done-signal. This *reverses* Pi's "workstreams never write Logseq" rule: the launched session is now responsible for keeping its dossier current, and its injected brief (§3.3) says so. The result is a self-reporting mesh: workstreams narrate themselves into shared memory; copilot curates the repo-level view over them.
- **Read/inject:** an MCP **resource** (`basecamp://memory/cockpit` + a dossier index) renders from the shared graph — the Tier-1 read resource `claude/README.md` already earmarked, now with a copilot consumer. Lazy-read discipline ("read the cockpit first; don't scan the graph") ports verbatim.
- **Naming/identity port unchanged:** `repo__<org>__<repo>`, `work__<org>__<repo>__<slug>`, `<org>/<name>` → `__`-sanitize. The record's `dossier_path` still points a workstream at its page; one repo cockpit still fans out to many dossiers.

Because the dossier is workstream-written and durable, it also becomes copilot's **primary status channel** (§3.5) — the self-report *is* the status.

### 3.3 Staging → native ephemeral worktrees, skill-bundled (fully native)

Staging maps onto Claude Code's native worktree machinery (`claude -w` / `EnterWorktree` / `ExitWorktree`, `worktree.baseRef`, `.claude/worktrees/`, `WorktreeCreate`/`WorktreeRemove` hooks), and the model **anchors on staging** rather than on a durable worktree:

- **Worktrees are ephemeral.** Native `.claude/worktrees/<name>` is created on demand and cleaned on exit. A workstream may use **several over time** (a new one per work session, or one per branch), and none is persisted. What persists is the **branch** the worktree sat on — the record retains branch names; git retains the branches.
- **The how-to lives in the skill, not a tool.** Rather than a `launch_workstream` MCP tool that shells out to git + tmux, the `copilot` skill *tells copilot how to stage*: name/create the branch, and instruct the user (or a launch step) to open a worktree on it with native tooling. Staging is guidance over native primitives; the only MCP call is recording the branch on the workstream (§3.4).
- **Handoff via the existing SessionStart hook.** When a Claude session opens on a workstream **branch** (resolved from the branch name, which encodes the slug — robust to ephemeral, possibly-multiple worktrees), the hook that already registers every session injects the current brief as SessionStart `additionalContext` and records the attaching `session_id` on the record. No launch flag, no Herdr — the workstream session is just *a Claude session on a workstream branch*, and the hook does the rest. The "fresh session only" guard maps to the `source: startup` matcher.

**Dropped:** the Herdr tmux pane (external; its job — get a session running on the branch — is `claude -w`/opening a worktree). On Claude Code for web there is no host worktree/tmux lifecycle, so this layer no-ops there (a known Tier-2 constraint); the record + dossier still work.

**Fidelity caveat:** SessionStart injects *context*, not a literal user turn (Pi's brief was a `sendUserMessage`). The session still starts knowing its brief; the difference is cosmetic. Verify the exact hook output contract against the pinned `claude` CLI version, as the team already does for hook payloads in [transcript-ingestion](./transcript-ingestion.md).

### 3.4 Records → a net-new schema in the Claude daemon (the irreducible core)

Durable, cross-session-queryable coordination records have no native analog (todos are session-scoped; files aren't queryable across sessions; background subagents are within-session — §6.8). So the record is the one daemon-backed piece — and it is a **net-new, clean-room schema in the Claude daemon**, *designed for this model*, not a port of the Pi `workstreams`/`workstream_versions`/`workstream_agents` tables. The Pi tables assumed a worktree-per-workstream and a swarm `agents` graph this model doesn't have.

**Proposed schema (net-new, in `hub/claude/store/`):**
- `workstreams` — `id` (`ws_<uuid>`), `slug` (unique three-word), `label`, `brief`, `constraints?`, `status` (`open`/`closed`), `dossier_path`, `created_at`, `updated_at`.
- `workstream_branches` — `workstream_id`, `repo`, `branch`, `created_at`, PK `(workstream_id, branch)`. The **retained git anchor(s)**; a workstream can hold several (multi-worktree / multi-repo). Replaces Pi's single worktree label.
- `workstream_sessions` — `workstream_id`, `session_id` (→ the Claude `sessions` table), `repo`, `branch`, `status`, `joined_at`, PK `(workstream_id, session_id)`. Additive attachment; liveness derives from the open `episodes` row; "which sessions/branches touched" derives here.

Notable simplifications vs Pi: **no `workstream_agents` swarm rows** (attachment is to the native `sessions` table, keyed by `session_id` carried in the POST body — there is no ambient WebSocket requester); **no worktree persistence** (branches instead). **Content versioning is a keep-or-drop** (§7): the workstream's own dossier now carries durable narrative history, which weakens Pi's "never strand a running agent" rationale for a `workstream_versions` table — the proposal is to **drop it for v1** and reintroduce only if record-level history proves necessary.

**The daemon delta (concrete):** a `WorkstreamsMixin` on `SessionStore`; POST bodies in `contract.py` (`create` / `edit` / `status` / `attach-branch` / `attach-session`) with a `CLAUDE_PROTOCOL_VERSION` bump 3 → 4 (health-gate respawns stale daemons — the existing pattern; keep DDL additive, no `ALTER`); routes (`POST /workstreams`, `POST /workstreams/{id}/edit|status|branch|attach`, `GET /workstreams`, `GET /workstreams/{id}`); client methods over the existing `httpx`-over-UDS transport; and the **id/slug generator** (the daemon never generated them; it lives in the MCP tool now, surfacing slug collisions as a retry). MCP tools land in `src/basecamp/mcp/tools/workstreams.py` (respecting the ≤500-line cap): `create_workstream`, `edit_workstream`, `list_workstreams`, `set_workstream_status` (staging is skill-driven, so `launch_workstream` reduces to a `record_branch` call).

### 3.5 Status → read the dossier, fork to escalate (mostly native)

Decision #5 (workstreams write their own dossier) resolves the status question that v1 left open. Copilot's need — *"what is workstream `<slug>` doing?"* — is answered in two tiers, cheapest first:

1. **Read the dossier (primary).** The workstream self-reports into `work__<org>__<repo>__<slug>` as it works, so the current state is *already in shared memory*. Copilot's "status" is a plain file read (or the `basecamp://memory` resource) — no live query, no session spawn, no interruption. This is the common case and it is fully native.
2. **Fork an ephemeral session (escalation).** When copilot needs something live the dossier doesn't capture, the **hub spawns a headless `claude -p` forked from the workstream session's transcript** — a *continuation from the main*, exactly your framing. The daemon already holds that transcript (path captured at SessionStart, nodes ingested), so it can fork a **copy** (non-perturbing, faithful to Pi's `ask_agent`) — or resume in place if a live nudge is genuinely wanted (perturbing; opt-in). The fork answers the question and is torn down. This is the daemon's one *active* role, and it reuses the built transcript store rather than any new mesh.

**Dropped:** `message_agent` (one-way push into a live session). It needs a cross-session channel Claude Code lacks, and it cuts against the posture. Copilot reads; it does not poke. The fork escalation covers the rare "I need to ask it something" case without a push channel.

This is strictly more native than v1's "read `transcript_nodes` and summarize": the primary path is a markdown read, and the escalation is a real Claude continuation rather than a bespoke summarizer.

---

## 4. The build, in two artifacts

**The plugin (`claude/`) — mostly native:**
- `skills/copilot/SKILL.md` — the copilot loop + the **staging how-to** (branch/worktree guidance), de-Pi'd, re-pointed at the MCP record tools.
- a companion **`workstream` skill** (or a section of the injected brief) telling a launched session to **maintain its own dossier**.
- `commands/copilot.md` *(optional)* — an explicit `/basecamp:copilot` entry.
- `src/basecamp/mcp/tools/workstreams.py` — `create_workstream`, `edit_workstream`, `list_workstreams`, `set_workstream_status`, `record_branch` (+ id/slug gen). No launch/pane tool.
- MCP resource `basecamp://memory/cockpit` (+ dossier index) over the shared graph.
- `src/basecamp/hooks/session.py` — SessionStart grows a branch: on a workstream branch, resolve the record, inject the brief as `additionalContext`, attach `session_id`.
- config — `logseq.graph_dir` as the **shared** memory location; no new launch flag.

**The daemon (`hub/claude/`) — the irreducible delta:** the net-new `WorkstreamsMixin` (`workstreams` + `workstream_branches` + `workstream_sessions`) + contract bodies (v4) + routes + client + the fork-to-answer path for §3.5's escalation.

Everything else copilot touches — project context, related dirs, session registration, transcript ingestion, the fail-open hook chain, the MCP instructions router — **already exists** from Tier-0/1 and the transcript work.

---

## 5. Sequencing

Three slices, ordered by value-per-cost:

- **C0 — Copilot as posture (pure native, zero daemon change).** The `copilot` skill (posture + staging how-to) + shared-Logseq memory files + the `basecamp://memory` read resource + native worktrees + the workstream-writes-its-own-dossier convention. Delivers an agent that orients you, makes the choice-set legible, stages workstreams as **branches + dossiers**, and curates the cockpit — with dossiers as the status channel. Ships without touching the daemon; a workstream at this tier is just a branch + a dossier. Highest value, lowest cost.
- **C1 — Durable records.** The net-new daemon schema (§3.4) + the create/edit/list/status/record-branch MCP tools + the SessionStart brief-injection hook. Adds queryable, cross-session, multi-branch coordination on top of the C0 branch+dossier convention.
- **C2 — Live status escalation.** The hub's forked-`claude -p` continuation (§3.5, tier 2). Only worth building once the dossier-read primary proves insufficient.

This maps onto the `claude/README.md` Tier-2 row but re-scopes it: cross-session *messaging* → cross-session *reading* (dossier + transcript fork), and worktree-lifecycle → branch-anchored ephemeral worktrees.

---

## 6. Native-capability audit (what the port relies on)

Confirmed against current Claude Code docs. Each is used or explicitly declined.

1. **Skills / commands / subagents in a plugin** — plugin-shippable, namespaced `plugin:name`, auto-surfaced by `description`. → the copilot **skill** (+ the workstream dossier skill) + entry command.
2. **Output styles** — plugin-shippable; `force-for-plugin` replaces the prompt wholesale but is **plugin-wide, not per-session**. → declined as default (skill is per-session); opt-in alternative.
3. **SessionStart hook** — plugin-shippable; emits `hookSpecificOutput.additionalContext` (context injection) and gates on a `source` matcher; **cannot inject a literal user turn**. → brief injection (verify per CLI version).
4. **PreToolUse deny** — `permissionDecision: "deny"` / exit 2, matcher by tool name. → *available* to enforce "copilot doesn't Edit/Write," **declined** per "don't port enforced modes"; discipline stays prose.
5. **Git worktrees** — `claude -w`, `EnterWorktree`/`ExitWorktree`, `worktree.baseRef`, `.claude/worktrees/`, `WorktreeCreate`/`WorktreeRemove` hooks, subagent `isolation: worktree`. `.claude/worktrees/` is **ephemeral by design** (auto-cleaned) — exactly the anchor-on-staging model. → the staging layer.
6. **Sessions & continuation** — independent sessions spawn via `claude -p` (headless) / the Agent SDK; a session **forks** (new id, self-contained transcript copy) or resumes (`--resume`/`-c`). **No native messaging between independent sessions** — they coordinate only through external channels (files, the daemon). → validates the status model: dossier files primary, a daemon-forked `claude -p` continuation for escalation.
7. **MCP `instructions` injection** — injected at session start; `claude/README.md` records an empirically-verified ~2KB truncation. Tools/resources surface as `mcp__basecamp__*`. → the memory resource + record tools; router stays lean, bulk in resources.
8. **Background subagents** — within-session only (shared session/permissions; `SendMessage`; `isolation: worktree`). **Not** independent sessions. → confirms a workstream session is *not* a subagent (that would re-introduce supervision); it is a separate `claude` session the record + dossier + transcript observe.

---

## 7. Open decisions

Recommendations given; none block C0.

1. **Content versioning of the record** — **drop for v1** (recommended: the workstream's dossier now carries durable narrative history) vs keep a `workstream_versions` table (Pi's "never strand a running agent" rationale, now weaker).
2. **Branch naming / slug encoding** — how a branch encodes its workstream so the SessionStart hook can resolve branch → record (e.g. a `<slug>` namespace or a `copilot/<slug>` prefix). Multi-branch workstreams need a scheme the hook can match.
3. **Worktree placement** — native `.claude/worktrees/<name>` (simplest, ephemeral) vs a `WorktreeCreate` hook that keeps a basecamp-owned path for setup-hook continuity. Recommend native default.
4. **Fork perturbation (status escalation)** — non-perturbing fork *copy* (recommended, faithful to `ask_agent`) vs an in-place resume that nudges the live session. Only relevant once C2 is built.
5. **Memory identity in a shared graph** — with one shared Logseq location across repos, confirm the `<org>/<name>` sanitization is collision-safe across every repo that shares the graph (it was per-repo in Pi).
6. **Brief-injection fidelity** — accept SessionStart `additionalContext` (context, not a user turn) after version-verifying, or fall back to a first-turn skill nudge.

---

## 8. Risks & caveats

- **Web sandbox.** Worktree/branch provisioning and local `claude -w` launch no-op on Claude Code for web. Records, memory (shared Logseq), and dossier-status still work. A known Tier-2 constraint.
- **MCP instructions cap.** ~2KB, truncated — keep the router a pointer, never the payload.
- **No literal user-turn injection.** The brief lands as context; verify the SessionStart contract against the pinned CLI.
- **No native cross-session push.** Status is pull-only (dossier read + fork escalation) by design; a push channel would require Routines and is out of scope.
- **Daemon protocol bump.** 3 → 4 respawns stale daemons via the health gate — the existing pattern; keep DDL additive.
- **Decentralized memory writes.** Many workstreams writing their own dossiers into one shared graph raises write-contention and consistency questions the Pi single-writer model avoided; dossiers are per-workstream files (no shared file), so contention is bounded, but the cockpit remains copilot-only to keep the repo-level view coherent.
- **Posture is not enforced.** "Copilot stages, doesn't implement" is prose, not a guard — §6.4's PreToolUse deny is the lever if enforcement is ever required.

---

## 9. In one line

Copilot decomposes into five layers; **four land on native Claude Code** — a skill for the posture, shared Logseq files (workstreams write their own dossiers) for memory, native ephemeral worktrees anchored on the *branch* for staging, and a dossier read (with a daemon-forked `claude -p` continuation to escalate) for status — leaving **one irreducible daemon piece**, a net-new workstream *record* that anchors a slug to its branches and dossier; the locked mode, full-prompt replacement, Herdr pane, WebSocket dispatch mesh, worktree persistence, and cross-session push all fall away, none surviving contact with what Claude Code already does.
