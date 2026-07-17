# Copilot on Claude Code — Port Proposal

**Status:** PROPOSAL (2026-07) · **Scope:** how the basecamp *repo copilot* (the `--copilot` posture + workstreams + repo memory) lands on Claude Code, native-first · **Builds on:** [claude-code-compatibility](./claude-code-compatibility.md), [`claude/README.md`](../../claude/README.md), [transcript-ingestion](./transcript-ingestion.md), [async-agents](./async-agents.md) · **Delivery:** the `claude/` plugin + the kept Claude hub daemon

This proposal turns the "🟡 dropped / optional Tier-2" copilot row of [claude-code-compatibility](./claude-code-compatibility.md) §4 into a concrete port. It examines the full copilot surface as built on Pi, then maps each mechanism to the **most native Claude Code feature that fits**, falling to the (already-kept) hub daemon only for the irreducible cross-session coordination core. Nothing here is built yet; this is the design record to argue over before code.

> **Revision v3 (2026-07) — Herdr-centric.** Supersedes the branch-anchored draft. Review settled the model on Pi's *shape* delivered on Claude Code natives: **Herdr is the environment** (copilot exists only in Herdr and is locked to it); `create_workstream` is **recoupled** — it mints the record, creates a **permanent** worktree, opens it in a **Herdr pane**, and **persists the worktree path** on the record; the workstream session boots via a **`/basecamp:start-workstream` skill** that pulls the record's **brief + dossier *path*** (the hub stores **pointers, not content**) and reads the dossier itself; the permanent worktree may spawn **ephemeral child worktrees**; Logseq splits into **journals** (time-stamped activity, per-workstream, unified into a daily view by native **Linked References**) and **dossiers** (durable state); workstreams stay **open until manually closed**, then get a **full teardown** (worktree removed, branch deleted, unmerged-work-guarded). §2–§10 reflect v3; §1 is the unchanged Pi-surface recap.

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

> For each copilot mechanism, take the **most native Claude Code feature that fits**. Fall to the **kept Claude daemon (via MCP tools)** only for state that is *irreducibly cross-session and durable* — a record that must outlive one session and be queried from another. Let git hold code, and let shared Logseq hold narrative; the daemon holds only **pointers and identity**, never content.

Applying it decomposes the monolithic "copilot mode" into six layers landing in **three** homes (plugin skill · shared Logseq · the Claude daemon). Only the workstream *record* needs the daemon, and even then only as a pointer store:

| Layer | Native-first port | Home | Native? |
|---|---|---|---|
| **Posture** (loop/persona, #1+#2) | a `copilot` **skill**, entered via `/basecamp:copilot`, **guarded to Herdr** (`HERDR_ENV`). Drop the hard mode-lock and the `plan()` guard. | native skill | ✅ native (soft guard) |
| **Memory** (#5) | markdown in a **shared Logseq graph** (native `Write`/`Edit`) + one MCP **read resource**. Split: copilot owns the **cockpit**; each workstream writes its own **dossier** (durable) and **journal blocks** (activity). | native + 1 MCP resource | ✅ native |
| **Staging** (#4) | **recoupled `create_workstream`** — record + **permanent** worktree + **Herdr pane**, worktree path persisted. | daemon tool + native worktree | ⚠️ tool over native worktrees |
| **Handoff** (#4) | a **`/basecamp:start-workstream` skill** pulling **brief + dossier path** via `basecamp workstream current`, then reading the dossier and attaching the session. | native skill + CLI | ✅ native |
| **Records** (#3) | a **net-new pointer schema in the Claude daemon** + MCP tools. Anchors slug → **worktree path**, branch, **dossier path**, status. | daemon + MCP tools | ⚠️ irreducible daemon core |
| **Status** (cross-session reach) | **read the workstream's own dossier + journal** (it self-reports into shared Logseq). No live query in the common case; a daemon-forked `claude -p` continuation is the optional escalation. | native file read | ✅ native |

### 2.1 The data model: anchor on staging

Pi's one durable artifact (a daemon-owned, worktree-bearing, versioned record) becomes **three durable anchors + a pointer record**, each in its natural store — and staging is the anchor:

- **The record** (the Claude daemon) — the durable coordination fact: identity (slug), brief, status, and **pointers** to the permanent worktree path, the branch, and the dossier page. Content lives elsewhere; the record points at it.
- **The permanent worktree + its branch** (git / disk) — the durable code anchor, at `~/.worktrees/<org>/<name>/copilot/<slug>/`. One home per workstream, **persisted on the record**. The execution session may additionally spin up **ephemeral child worktrees** (native `.claude/worktrees/`, auto-cleaned) for isolation — those are disposable and never persisted.
- **The dossier + journal** (shared Logseq) — the durable narrative anchor, **written by the workstream itself**: the dossier holds durable state (decisions, blockers, done-signal); dated journal blocks hold the activity log.

A workstream is therefore **1 record → 1 permanent worktree (+ N ephemeral children) → 1 branch → 1 dossier (+ dated journal blocks)**. Copilot *stages* (mints the record, provisions the worktree + pane, seeds the dossier); the workstream session *executes and self-reports*; copilot later *reads the self-report* to roll up. "Which sessions touched it" derives from the record's session rows.

### 2.2 Herdr is the environment

Unlike the branch-anchored draft, v3 **keeps Herdr** as the operating environment. Copilot runs in a Herdr primary pane; each workstream runs in its own Herdr pane on its worktree; `create_workstream` opens that pane. This is a deliberate product choice — the Herdr multi-pane workspace *is* the copilot cockpit — and it makes the handoff concrete (a real pane the user drops into) rather than an instruction to open a worktree by hand. The cost is that the staging/handoff layers are **local-only** (no host tmux in Claude Code for web); records, memory, and status still work there.

---

## 3. Layer-by-layer mapping

### 3.1 Posture → a Herdr-locked `copilot` skill (native, soft guard)

The copilot loop — orient, reconcile signals, make the choice-set legible, shape workstreams, curate the cockpit — is prose guidance. It ports to a native **skill** (`skills/copilot/SKILL.md`), the same shape as the landed `planning`, `gather`, and `pr` skills. `modes/copilot.md` becomes the skill body almost verbatim; edits strip Pi-runtime jargon (per the compat doc's model-facing-content principle) and re-point tool references at the new MCP tools.

Entry is `/basecamp:copilot` (skills auto-namespace `plugin:name` and can auto-surface by description) — deliberately *per-session*.

**Herdr lock — a skill-entry guard, honestly soft.** "Copilot only exists in Herdr" ports as a guard at the skill's front door: it checks the Herdr env (`HERDR_ENV === "1"`, with `HERDR_SOCKET_PATH` / `HERDR_PANE_ID` present — the exact `shouldOpenWorkstreamInHerdr` signals, verified live) and, outside Herdr, refuses to adopt the posture and tells the user to launch copilot from Herdr. This is a **guardrail at the one entry point that matters**, not Pi's immutable mode: Claude Code has no lockable session mode, so there is no hard wall (a user could still do copilot-ish things by hand). If a harder gate is ever wanted, a `SessionStart`/`PreToolUse` hook keyed on `HERDR_ENV` is the lever — but per the compat doc's "don't port enforced modes," the skill guard is the v1 answer.

**Dropped, safely:** the immutable mode-lock (soft skill guard instead) and the `plan()` hide (native plan mode is fine; copilot just won't lean on it).

**Alternative — an output style.** Plugins can ship output styles that replace the prompt wholesale (`force-for-plugin: true` + `keep-coding-instructions: false` = Pi's exact "mode replaces the prompt"). Declined as default: `force-for-plugin` is **plugin-wide, not per-session**, so it can't be launch-conditional the way `--copilot` was. Kept as an opt-in for a copilot-dedicated install.

### 3.2 Memory → shared Logseq: dossiers (durable) + journals (activity)

Logseq stays — it is just markdown — and it **becomes a shared location**: one graph, visible across repos and sessions, the substrate both copilot and workstreams read and write. This is the most native layer (plain `Write`/`Edit` on `.md` files), and v3 sharpens it into a three-page-kind operating model plus one decentralization change from Pi.

**Three page kinds, three jobs:**
- **Cockpit** (`repo__<org>__<repo>`, in `pages/`) — copilot-owned repo-level roll-up: current focus, priority shifts, the choice-set, cross-workstream decisions.
- **Dossier** (`work__<org>__<repo>__<slug>`, in `pages/`) — the durable curated record of *one* workstream: current state, sticky decisions, open questions, done-signal. **Written by the workstream itself.**
- **Journal** (`journals/YYYY_MM_DD.md`) — the time-stamped activity log ("DONE X, blocked on Y today").

**Writes decentralize (the change from Pi).** Pi made copilot the sole Logseq writer and barred workstreams. v3 reverses that for the per-workstream record: **each workstream writes its own dossier and its own journal blocks**; copilot owns only the cockpit. The result is a self-reporting mesh — workstreams narrate themselves into shared memory; copilot curates the repo-level view over them. The `/basecamp:start-workstream` skill (§3.3) carries this operating guidance into the execution session.

**Broken-up journals, one unified daily view — via Logseq Linked References (native).** The obvious worry with many workstreams logging activity is write-contention on a shared daily file. Logseq's core backlink feature dissolves it: each workstream writes its dated activity as blocks **in its own page**, each block tagging the day, e.g. `- DONE shipped retry backoff [[Jul 17th, 2026]]`. The daily journal page stays thin; Logseq's **Linked References** automatically assemble *every* workstream's blocks that tagged that day into one consolidated day view — for free, no custom machinery. So: **unified daily view** (the journal's Linked References) + **zero write contention** (each workstream touches only its own file) + **native** (standard backlink graph). The same mechanism stitches a workstream's timeline onto its dossier when blocks also tag `[[work__<org>__<repo>__<slug>]]`.

- **Read/inject:** an MCP **resource** (`basecamp://memory/cockpit` + a dossier index) renders from the shared graph — the Tier-1 read resource `claude/README.md` already earmarked, now with a copilot consumer. Lazy-read discipline ("read the cockpit first; don't scan the graph") ports verbatim.
- **Naming/identity port unchanged:** `repo__<org>__<repo>`, `work__<org>__<repo>__<slug>`, and `safeRepoIdentity` (`<org>/<name>` → `org__name` via `.replaceAll("/","__").replace(/[^A-Za-z0-9._-]/g,"_")`). `readLogseqGraphDir` still requires `logseq.graph_dir` to resolve to an existing directory.

**Grounding caveat.** Journals **do not exist in code today** — `pi/core/project/logseq.ts` touches only `pages/`. The sole existing convention is the style doc `pi/system-prompt/defaults/styles/logseq.md` naming `journals/YYYY_MM_DD.md`. This design *adds* journal usage; the skill supplies the operating guidance (including that the day link must be written in the graph's configured date format so references resolve — Logseq displays `[[Jul 17th, 2026]]` but stores `journals/2026_07_17.md`). Nothing enforces it in code.

Because the dossier + journal are workstream-written and durable, they are also copilot's **status channel** (§3.5) — the self-report *is* the status.

### 3.3 Staging & handoff → recoupled `create_workstream` + a start skill

v3 **recouples** create and launch (Pi decoupled them) and **keeps the Herdr pane**. Staging is one call; handoff is one skill.

**`create_workstream` (one tool, one call).** Copilot, having shaped the work, calls it and it does everything in order:
1. mints the record (slug) in the Claude daemon;
2. `git worktree add`s the **permanent** worktree at `~/.worktrees/<org>/<name>/copilot/<slug>/` on branch `<user-prefix>/<slug>` (the existing `copilot/` label namespace and `copilotWorktreeTarget` naming carry over);
3. opens that worktree in a **Herdr pane** (the existing `herdr worktree open` path, gated by `shouldOpenWorkstreamInHerdr`);
4. **persists the worktree path + branch** on the record;
5. seeds/links the dossier (records `dossier_path`; optionally writes a dossier stub).

Output is a live Herdr pane sitting in the workstream's own worktree, plus a durable record that knows where that worktree is. Steps 2–5 are best-effort-aware: a failed pane open still yields a valid record + worktree (the user can open the pane manually), mirroring Pi's best-effort Herdr handling.

**`/basecamp:start-workstream` (the handoff skill).** In the new pane the user runs `claude`, then invokes the skill. It:
1. runs `basecamp workstream current` — a **new CLI subcommand** that asks the Claude daemon (over the existing `httpx`-over-UDS transport) "which workstream owns *this* worktree path/branch?" and prints the record's **brief + dossier *path*** (**pointers, not content** — the hub never stores the dossier body);
2. **reads the dossier file itself** with the Read tool (and the cockpit if relevant);
3. **attaches** the session — records this `session_id` on the workstream (an additive session row);
4. adopts the **execution posture** and the Logseq operating guidance (keep your dossier current; log dated activity blocks).

This replaces Pi's `pi --workstream` boot. Two payoffs over the branch-anchored draft: it **sidesteps the SessionStart-hook fidelity problem** (no reliance on `additionalContext` injecting a pseudo-user-turn — the user explicitly pulls context via the skill), and it keeps the hub as a **pointer store** (brief + paths), never a content store.

**Ephemeral child worktrees.** Inside its permanent worktree, the execution session may create native `.claude/worktrees/` children for isolated sub-work; those auto-clean and are never persisted. Only the permanent worktree is the workstream's home.

Why a `basecamp workstream current` CLI subcommand (not an MCP tool): the pull happens *before* the workstream session is meaningfully underway and is a plain daemon read; a CLI call the skill inlines is the lightest thing that works, reuses the `hub/claude/client` transport, and needs no MCP round-trip. It lands as a `workstream` Click group (`@workstream.command("current")`) attached via `basecamp.add_command(...)`, the repo's existing idiom.

### 3.4 Records → a net-new pointer schema in the Claude daemon (the irreducible core)

Durable, cross-session-queryable coordination records have no native analog (todos are session-scoped; files aren't queryable across sessions; background subagents are within-session — §6.8). So the record is the one daemon-backed piece — a **net-new, clean-room schema in the Claude daemon**, designed for this model, not a port of the Pi `workstreams`/`workstream_versions`/`workstream_agents` tables (which assumed a swarm `agents` graph and a non-persisted worktree this model doesn't have).

**Proposed schema (net-new, in `hub/claude/store/`):**
- `workstreams` — `id` (`ws_<uuid>`), `slug` (unique three-word), `label`, `brief`, `status` (`open`/`closed`), **`worktree_path`**, **`branch`**, `repo`, `dossier_path`, `created_at`, `updated_at`. The record is a **pointer bundle**: identity + brief + where the worktree / branch / dossier live. `worktree_path` persistence is what lets `basecamp workstream current` resolve worktree → record directly (Pi could not — it recovered the mapping from the `copilot/<slug>` label).
- `workstream_sessions` — `workstream_id`, `session_id` (→ the Claude `sessions` table), `repo`, `status`, `joined_at`, PK `(workstream_id, session_id)`. Additive attachment (a workstream can have several sessions over time); liveness derives from the open `episodes` row.

Notable simplifications vs Pi: **no `workstream_agents` swarm rows** (attachment is to the native `sessions` table, keyed by the `session_id` carried in the attach POST body — there is no ambient WebSocket requester); **worktree path persisted** (one permanent home, not a re-derived label); **content versioning dropped for v1** — the workstream's own dossier + journal now carry durable narrative history, which retires Pi's "never strand a running agent" rationale for a `workstream_versions` table (reintroduce only if record-level history proves necessary — §7).

**The daemon delta (concrete):** a `WorkstreamsMixin` on `SessionStore` (create-if-not-exists DDL, additive, no `ALTER`); POST bodies in `contract.py` (`create` / `edit` / `status` / `attach-session`) with a `CLAUDE_PROTOCOL_VERSION` bump 3 → 4 (health-gate respawns stale daemons — the existing pattern); routes (`POST /workstreams`, `POST /workstreams/{id}/edit|status|attach`, `GET /workstreams`, `GET /workstreams/{id}`, and a `GET /workstreams/by-worktree?path=` for `current`); client methods over the existing transport; and the **id/slug generator** (the daemon never generated them — it lives in the MCP tool now, surfacing slug collisions as a retry). MCP tools land in `src/basecamp/mcp/tools/workstreams.py` (respecting the ≤500-line cap): `create_workstream` (record + worktree + pane, §3.3), `edit_workstream`, `list_workstreams`, `set_workstream_status`.

### 3.5 Status → read the dossier + journal (native), fork to escalate (optional)

Because workstreams now self-report into shared Logseq, the status question — *"what is workstream `<slug>` doing?"* — is answered by a **file read**, cheapest first:

1. **Read the dossier + recent journal (primary, fully native).** The workstream keeps its dossier current and logs dated activity blocks, so the current state and the recent timeline are *already in shared memory*. Copilot's "status" is a plain read (dossier page for durable state; the day's journal Linked References for what happened) — no live query, no session spawn, no interruption. This is the common case.
2. **Fork an ephemeral `claude -p` (escalation, optional).** When copilot needs something live the dossier doesn't capture, the hub can spawn a headless `claude -p` **forked from the workstream session's transcript** (a *copy* — non-perturbing, faithful to Pi's `ask_agent`); the daemon already holds that transcript. The fork answers and is torn down. This is the daemon's one *active* role and reuses the built transcript store rather than any new mesh — but it is **C2, build-if-needed**, not part of the common path.

**Dropped:** `message_agent` (one-way push into a live session). It needs a cross-session channel Claude Code lacks and cuts against the posture. Copilot reads; it does not poke.

### 3.6 Cleanup → manual close, full teardown, unmerged-guarded (new)

Workstreams stay `open` until **manually closed** — there is no auto-close. Copilot works with the user to review done/stale workstreams and, on close:
1. `set_workstream_status(closed)` on the record;
2. **full teardown** — `git worktree remove` the permanent worktree **and** `git branch -d` the branch.

Because this is destructive and user-driven, teardown **guards unmerged work**: it uses `git branch -d` semantics (refuses a branch with commits not merged to its base) and only escalates to `git branch -D` (or `worktree remove --force`) after an explicit user confirmation — never a silent force-delete. A workstream whose branch is unmerged is surfaced ("this has unmerged commits — merge, or confirm discard") rather than reaped. Ephemeral child worktrees need no teardown step (native auto-clean). This is a small `cleanup_workstream` helper the copilot skill drives; the record's persisted `worktree_path`/`branch` are exactly what it needs.

---

## 4. The build

**The plugin (`claude/`):**
- `skills/copilot/SKILL.md` — the copilot loop, de-Pi'd, **Herdr-guarded**, re-pointed at the MCP tools; drives staging (`create_workstream`) and cleanup.
- `skills/start-workstream/SKILL.md` — the handoff skill: `basecamp workstream current` → read dossier → attach → execution posture + Logseq operating guidance (own your dossier; log dated journal blocks).
- `commands/copilot.md` *(optional)* — an explicit `/basecamp:copilot` entry.
- `src/basecamp/mcp/tools/workstreams.py` — `create_workstream` (record + permanent worktree + Herdr pane + persist path), `edit_workstream`, `list_workstreams`, `set_workstream_status` (+ id/slug gen).
- MCP resource `basecamp://memory/cockpit` (+ dossier index) over the shared graph.
- `src/basecamp/core/cli/workstream_group.py` — the `workstream` Click group; `workstream current` (resolve worktree → record via the daemon, print brief + dossier path).
- config — `logseq.graph_dir` as the **shared** memory location.

**The daemon (`hub/claude/`) — the irreducible delta:** the net-new `WorkstreamsMixin` (`workstreams` + `workstream_sessions`, with `worktree_path`/`branch`/`dossier_path` persisted) + contract bodies (v4) + routes (incl. `by-worktree` lookup) + client methods. The `claude -p` fork path (§3.5) is C2-only.

Everything else copilot touches — project context, related dirs, session registration, transcript ingestion, the fail-open hook chain, the MCP instructions router, the `~/.worktrees/<org>/<name>/` root and `copilot/<slug>` label namespace, the `herdr worktree open` path — **already exists** from Tier-0/1, the transcript work, and the Pi worktree/Herdr machinery being reused.

---

## 5. Sequencing

Three slices, ordered by value-per-cost:

- **C0 — Copilot as posture (pure native, zero daemon change).** The Herdr-guarded `copilot` skill + shared-Logseq memory (cockpit + dossiers + journals with Linked References) + the `basecamp://memory` read resource. At C0 a "workstream" is a hand-made worktree + a dossier the copilot seeds and the user maintains — no record, no `create_workstream`. Delivers an agent that orients you, makes the choice-set legible, and curates the cockpit, with dossiers/journals as the status channel. Highest value, lowest cost.
- **C1 — Records + recoupled staging + handoff.** The net-new daemon schema (§3.4) + `create_workstream` (record + permanent worktree + Herdr pane) + the `/basecamp:start-workstream` skill + `basecamp workstream current` + `set_workstream_status` + cleanup teardown. Turns the C0 convention into durable, queryable, pane-provisioned staging.
- **C2 — Live status escalation.** The hub's forked-`claude -p` continuation (§3.5, tier 2). Build only once the dossier/journal read proves insufficient.

This maps onto the `claude/README.md` Tier-2 row but re-scopes it: cross-session *messaging* → cross-session *reading* (dossier + journal, transcript fork as escalation), and Pi's swarm coordination → a pointer record over native worktrees + Herdr.

---

## 6. Native-capability audit (what the port relies on)

Confirmed against current Claude Code docs. Each is used or explicitly declined.

1. **Skills / commands / subagents in a plugin** — plugin-shippable, namespaced `plugin:name`, auto-surfaced by `description`. → the `copilot` + `start-workstream` skills + entry command.
2. **Output styles** — plugin-shippable; `force-for-plugin` replaces the prompt wholesale but is **plugin-wide, not per-session**. → declined as default (skill is per-session); opt-in alternative.
3. **SessionStart hook** — plugin-shippable; emits `hookSpecificOutput.additionalContext` and gates on a `source` matcher; **cannot inject a literal user turn**. → *not* on the handoff path anymore (the `start-workstream` skill pulls context explicitly); still used for the existing session-registration hook.
4. **PreToolUse deny** — `permissionDecision: "deny"` / exit 2, matcher by tool name. → *available* to harden the Herdr lock or "copilot doesn't Edit/Write," **declined** per "don't port enforced modes"; the Herdr guard is skill prose.
5. **Git worktrees** — `claude -w`, `EnterWorktree`/`ExitWorktree`, `worktree.baseRef`, `.claude/worktrees/`, `WorktreeCreate`/`WorktreeRemove` hooks, subagent `isolation: worktree`. → **ephemeral child** worktrees (native `.claude/worktrees/`); the **permanent** workstream worktree stays on the basecamp `~/.worktrees/<org>/<name>/copilot/<slug>/` root (reused Pi machinery), persisted on the record.
6. **Sessions & continuation** — independent sessions spawn via `claude -p` / the Agent SDK; a session **forks** (new id, self-contained transcript copy) or resumes. **No native messaging between independent sessions** — they coordinate only through external channels (files, the daemon). → validates status-by-file-read (primary) + the optional daemon-forked `claude -p` escalation.
7. **MCP `instructions` + tools/resources** — instructions injected at session start (`claude/README.md` records a ~2KB truncation); tools/resources surface as `mcp__basecamp__*`. → the memory resource + workstream tools; router stays a lean pointer.
8. **Background subagents** — within-session only (shared session/permissions; `SendMessage`; `isolation: worktree`). **Not** independent sessions. → confirms a workstream session is *not* a subagent (that would re-introduce supervision); it is a separate `claude` session in its own Herdr pane that the record + dossier + transcript observe.
9. **Herdr environment** — detected via `HERDR_ENV=1` + `HERDR_SOCKET_PATH` + `HERDR_PANE_ID` (+ `HERDR_WORKSPACE_ID`), verified live in a teleported session. → the copilot Herdr guard and the `create_workstream` pane open (`herdr worktree open`). External to Claude Code; local-only.

---

## 7. Open decisions

Recommendations given; C0 is unblocked regardless.

1. **Record content versioning** — **drop for v1** (recommended: dossier + journal carry durable history) vs keep a `workstream_versions` table.
2. **Memory identity in a shared graph** — with one shared Logseq graph across repos, confirm `safeRepoIdentity` (`<org>/<name>` → `org__name`) is collision-safe across every repo sharing the graph (it was effectively per-repo in Pi). Low risk, worth a check before it's load-bearing.
3. **Journal granularity** — dated blocks **on the dossier page** (fewer files; the dossier *is* the workstream's home) vs a dedicated per-workstream `work-log__…__<slug>` page (cleaner separation of durable-state vs activity). Either yields the unified daily view via Linked References; recommend dossier-blocks for v1 simplicity.
4. **Herdr-lock hardness** — skill-entry guard (recommended, per "don't port enforced modes") vs a `SessionStart`/`PreToolUse` hook that hard-gates copilot to `HERDR_ENV`. Escalate only if the soft guard proves insufficient.
5. **Fork perturbation (C2 escalation)** — non-perturbing fork *copy* (recommended, faithful to `ask_agent`) vs an in-place resume that nudges the live session.

## 8. Confirmed decisions

Settled in review; baked into §2–§6.

1. **Herdr is the environment; copilot is locked to it** (soft skill-entry guard — §3.1, §2.2).
2. **`create_workstream` is recoupled** — record + permanent worktree + Herdr pane, worktree path persisted (§3.3, §3.4).
3. **`/basecamp:start-workstream` is a skill**; it pulls **brief + dossier *path*** (pointers, not content) via `basecamp workstream current`, then reads the dossier itself (§3.3).
4. **Permanent workstream worktree; ephemeral child worktrees** under it (§2.1, §3.3).
5. **Logseq: journals (activity, per-workstream, unified via Linked References) + dossiers (durable); hub stores pointers, not content** (§3.2).
6. **Workstreams stay open until manually closed; close does a full teardown** (worktree removed + branch deleted, unmerged-work-guarded) (§3.6).
7. **`current` lookup is hub-authoritative** — the record persists the worktree path; the daemon answers "which workstream owns this worktree?" (§3.3, §3.4).

---

## 9. Risks & caveats

- **Local-only staging/handoff.** `create_workstream`'s worktree + Herdr pane and the `start-workstream` handoff are host-local; in Claude Code for web (no tmux/host worktree lifecycle) they no-op. Records, memory (shared Logseq), and status still work. A known Tier-2 constraint — now larger, because v3 leans on Herdr by design.
- **Herdr lock is soft.** The skill guard is a front-door check, not a wall; a determined user can bypass it. Acceptable per "don't port enforced modes"; §7.4 is the harder lever if needed.
- **Journals are net-new.** No code writes Logseq journals today; the day-link must match the graph's date format for Linked References to resolve. Skill-supplied guidance, not code-enforced.
- **Destructive cleanup.** Full teardown deletes a branch — the unmerged-work guard (never a silent `-D`) is load-bearing; get it right before shipping C1.
- **Daemon protocol bump.** 3 → 4 respawns stale daemons via the health gate — the existing pattern; keep DDL additive.
- **MCP instructions cap.** ~2KB, truncated — keep the router a pointer, never the payload.
- **Decentralized memory writes.** Many workstreams writing their own dossiers/journals into one shared graph; because each touches only its own file (and the daily view is assembled by Linked References, not a shared file), contention is bounded. The cockpit stays copilot-only to keep the repo-level view coherent.

---

## 10. In one line

Copilot lands on Claude Code as a **Herdr-guarded skill** whose loop stages work with one recoupled `create_workstream` (record + **permanent** worktree + Herdr pane, path persisted), hands off via a `/basecamp:start-workstream` skill that pulls **pointers, not content** from a **net-new pointer record** in the kept Claude daemon, and reads status straight from the workstream's **self-written dossier + journals** (unified by Logseq Linked References) — retiring Pi's locked mode, full-prompt replacement, WebSocket dispatch mesh, and cross-session push, while keeping exactly the one irreducible thing Claude Code can't do natively: a durable record that outlives a session and can be queried from another.
