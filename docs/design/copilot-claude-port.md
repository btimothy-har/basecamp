# Copilot on Claude Code — Port Proposal

**Status:** PROPOSAL (2026-07) · **Scope:** how the basecamp *repo copilot* (the `--copilot` posture + workstreams + repo memory) lands on Claude Code, native-first · **Builds on:** [claude-code-compatibility](./claude-code-compatibility.md), [`claude/README.md`](../../claude/README.md), [transcript-ingestion](./transcript-ingestion.md), [async-agents](./async-agents.md) · **Delivery:** the `claude/` plugin + the kept Claude hub daemon

This proposal turns the "🟡 dropped / optional Tier-2" copilot row of [claude-code-compatibility](./claude-code-compatibility.md) §4 into a concrete port. It examines the full copilot surface as built on Pi, then maps each mechanism to the **most native Claude Code feature that fits**, falling to the (already-kept) hub daemon only for the irreducible cross-session coordination core. Nothing here is built yet; this is the design record to argue over before code.

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

> For each copilot mechanism, take the **most native Claude Code feature that fits**. Fall to the **kept Claude daemon (via MCP tools/resources)** only for state that is *irreducibly cross-session and durable* — records that must outlive one session and be queried from another. That is exactly the one thing the compat doc decided to keep the daemon for.

Applying it decomposes the monolithic "copilot mode" into five layers that land in **three** homes — and **three of the five are fully native**, needing no daemon at all:

| Layer | Native-first port | Home | Native? |
|---|---|---|---|
| **Posture** (loop/persona, #1+#2) | a `copilot` **skill** (the loop, verbatim-adapted), entered via `/basecamp:copilot`. Drop the mode-lock and the `plan()` guard. | native skill | ✅ fully native |
| **Memory** (#5) | markdown **files** (native `Write`/`Edit`; sole-writer becomes a posture rule in the skill) + one MCP **read resource** for injection. Naming convention ports verbatim. | native + 1 MCP resource | ✅ native |
| **Staging-worktree** (#4, the worktree half) | native worktrees (`claude -w` / `EnterWorktree` / `git worktree`) + a **SessionStart hook** that injects the brief when a session opens in a `copilot/<slug>` worktree. Drop Herdr. | native worktree + existing hook | ✅ native |
| **Records** (#3) | **MCP tools over the kept Claude daemon** (extend `hub/claude` with a workstreams store + routes + client + protocol bump). Reuse the portable Pi schema/logic. Dossier stays the human-facing source of truth. | daemon + MCP tools | ⚠️ irreducible daemon core |
| **Status** (the cross-session-reach half of #4) | a `workstream_status` MCP tool that **reads the already-ingested transcript** (join workstream → agents → sessions → episodes → `transcript_nodes`) and summarizes — non-interrupting, exactly like `ask_agent`'s fork, but on infra that already landed. Drop `message_agent` push. | daemon + MCP tool | ⚠️ daemon core, reuses built ingestion |

The native-capability audit behind these verdicts (all confirmed against current Claude Code docs) is in §6.

---

## 3. Layer-by-layer mapping

### 3.1 Posture → a `copilot` skill (fully native)

The copilot loop — orient, reconcile signals, make the choice-set legible, shape workstreams, curate memory — is prose guidance. It ports to a native **skill** (`skills/copilot/SKILL.md`), the same shape as the already-landed `planning`, `gather`, and `pr` skills. `modes/copilot.md` becomes the skill body almost verbatim; the only edits strip Pi-runtime jargon (per the compat doc's model-facing-content principle) and re-point tool references at the new MCP tools.

Entry is a **slash command / skill invocation** `/basecamp:copilot` (skills auto-namespace as `plugin:name` and can also auto-surface by description match). This is deliberately *per-session*, not global.

**What we drop, and why it is safe:**
- **The mode-lock (immutability).** Claude Code has no lockable, cyclable "agent mode," and the compat doc + `claude/README.md` both say don't port enforced modes. Copilot becomes a *posture you enter*, not a *mode that traps you*. The discipline ("stage, don't implement") lives in the skill prose.
- **The `plan()` hide.** Native plan mode is fine and useful; copilot simply won't lean on it. The two-layer Pi guard has nothing to guard.

**Alternative considered — an output style.** Claude Code plugins *can* ship output styles (`output-styles/*.md`) that replace the system prompt wholesale, and `force-for-plugin: true` + `keep-coding-instructions: false` would reproduce Pi's "mode replaces the whole prompt" exactly. Rejected as the default because `force-for-plugin` is **plugin-wide, not launch-conditional** — it would force copilot on *every* session of the plugin, which is wrong (copilot is one posture among many). A skill is per-session and composes with Claude Code's own tool/safety guidance (which the compat doc explicitly wants to keep). Output style stays available as an opt-in for a user who wants a dedicated "copilot-only" install.

### 3.2 Memory → files + one MCP resource (fully native)

The cockpit and dossiers are already plain markdown; copilot already writes them with ordinary file edits. On Claude Code this is the *most* native layer:

- **Write:** native `Write`/`Edit`. "Copilot is the sole writer of repo memory; read-only sessions propose instead of writing" becomes a rule in the skill, not a runtime guard (there is no runtime to guard it, and none is needed — it is a discipline, not a safety property).
- **Read/inject:** an MCP **resource** — `basecamp://memory/cockpit` (and a dossier index) — rendered by the MCP server from the graph dir. This is the Tier-1 "Logseq repo-memory resource" the `claude/README.md` inventory already earmarked; it just gains a copilot consumer. Lazy-read discipline ("read the cockpit first; do not scan the whole graph") ports verbatim as resource/skill text.
- **Naming convention ports unchanged:** `repo__<org>__<repo>` cockpit, `work__<org>__<repo>__<slug>` dossiers, `<org>/<name>` → `__`-and-sanitize identity. `source_dossier_path` on a workstream record still points a workstream at its dossier; one dossier still fans out to many workstreams.

Open question: keep `logseq.graph_dir` (Logseq continuity) or a repo-relative `.basecamp/memory/` (self-contained, travels with the repo). See §7.

### 3.3 Staging-worktree → native worktrees + a SessionStart brief hook (fully native)

`launch_workstream`'s worktree half maps cleanly onto Claude Code's **native worktree machinery** (confirmed comprehensive in §6): `claude -w <name>` / `EnterWorktree` / `ExitWorktree`, `worktree.baseRef`, `.claude/worktrees/`, and `WorktreeCreate`/`WorktreeRemove` hooks for custom placement. The `copilot/<slug>` label convention survives as the worktree name.

The elegant part is the **handoff**. In Pi, `pi --workstream` on a fresh session attaches an agent row and injects the brief. On Claude Code, the **SessionStart hook that already registers every session** (`basecamp-hook session-start`) grows one branch: if the session's `BASECAMP_WORKTREE_LABEL` (or branch) matches `copilot/<slug>`, resolve the workstream from the daemon, **inject the brief as SessionStart `additionalContext`**, and record the attaching `session_id` on the workstream (the attach). No new launch flag, no separate mechanism — the workstream session is just *a Claude session that happens to open in a `copilot/<slug>` worktree*, and the hook does the rest. The "genuinely fresh session only" guard maps to the SessionStart `source` matcher (`startup`, not `resume`/`compact`).

**What we drop:** the **Herdr tmux pane**. It is an external tool (the compat doc lists Herdr as external/optional), and its purpose — get a session running in the worktree — is served by launching `claude` there. Locally that is `cd <worktree> && claude` (or `claude -w`); the staging tool just prints the command (or auto-launches — see §7). On Claude Code for web there is no host tmux, so this half no-ops there regardless (a known Tier-2 constraint).

**Fidelity caveat:** a SessionStart hook injects *context*, not a literal user turn (Pi's brief is a `sendUserMessage`). Functionally the session still starts knowing its brief; the difference is cosmetic. This should be verified against the pinned `claude` CLI version exactly as the team already version-verifies hook payloads in [transcript-ingestion](./transcript-ingestion.md) §2.

### 3.4 Records → MCP tools over the kept Claude daemon (the irreducible core)

Durable, versioned, slug-identified, cross-session-queryable coordination records have **no native analog** — native todos are session-scoped, skills/files are not queryable across sessions, and background subagents are within-session (§6.8). This is precisely the state the compat doc kept the daemon for. So the records layer is the one place we build daemon-backed MCP tools — and it reuses a lot.

**Reuse (as-is or nearly):** the Pi `hub/store/workstreams/` schema (the three tables, versioning, additive attachment) is plain SQLite with no Pi-runtime coupling; the service handlers are a thin store→status-code mapping; the read queries (`get_workstream_with_agents`, `list_workstreams(status/repo/dossier_path/query)`) map 1:1 onto routes. `claude/README.md` already earmarked Workstreams as "MCP tools + resource, Tier 2, daemon-backed."

**The delta (concrete):**
1. **`hub/claude/store/`** — add a `WorkstreamsMixin` to `SessionStore` (the `workstreams`, `workstream_versions`, `workstream_agents` tables, ported from Pi). One change: `workstream_agents.agent_id` joins to the Claude **`sessions`** table (there is no Pi `agents` graph here), with liveness from the open **`episodes`** row. The `repo`/`worktree_label` facets already exist on `sessions`, so "which repos touched" derives cleanly.
2. **`hub/claude/contract.py`** — re-express the four Pi WS frames as HTTP POST bodies (`create` / `revise` / `status` / `attach`); the field sets and ack-status enums (`created`/`slug_conflict`/… , `revised`+`version`, `updated`/`not_found`/`invalid_status`, `attached`/`not_found`) carry over verbatim. Bump `CLAUDE_PROTOCOL_VERSION` 3 → 4 (the health gate respawns stale daemons — an existing pattern).
3. **`hub/claude/routes.py`** — `POST /workstreams`, `POST /workstreams/{id}/revise`, `POST /workstreams/{id}/status`, `POST /workstreams/{id}/attach`, `GET /workstreams`, `GET /workstreams/{id}`.
4. **`hub/claude/client/`** — client methods over the existing `httpx`-over-UDS transport and `ensure_daemon` bootstrap.
5. **`src/basecamp/mcp/tools/workstreams.py`** — the MCP tools (`@mcp.tool` in `build_server()`; land the impl in a `mcp/tools/` subpackage to respect the ≤500-line cap). The MCP server is long-lived per session, so it holds the client. **The id/slug generator moves here** (the daemon never generated them — the Pi TS side did); slug-uniqueness collisions surface as a retry, matching the Pi `slug_conflict` semantics.

Attach identity changes shape: Pi keyed attach off the live WebSocket's `requester_node_id`; a stateless HTTP daemon has no ambient requester, so the attaching `session_id` travels **in the POST body** (the SessionStart hook already knows it).

### 3.5 Status → daemon transcript-read (reuses built ingestion)

Copilot's cross-session need is narrow and specific: *"give me a concise current-state summary of workstream `<slug>`'s agent session(s), without interrupting them."* Pi served this with `ask_agent` — a fork of the target's transcript file, answered from that snapshot. The native audit (§6.6) confirms Claude Code has **no cross-session messaging** primitive (`SendMessage` is within-session; independent sessions coordinate only through external channels). So `ask_agent` has no drop-in.

But the Claude daemon **already is that external channel, and already holds the data**: every workstream session's transcript is ingested into `transcript_nodes`, tagged with its `session_id`/`repo`/`worktree_label`. So status becomes a **daemon read**, not a fork:

> `workstream_status(slug)` → join `workstreams → workstream_agents → sessions → episodes` (liveness) and read the latest `transcript_nodes` for those sessions → return a summary (last N assistant turns, or a cheap `fast`-model reduction).

This is the *same* semantics `ask_agent` gave (read a snapshot, don't perturb the target) but on infrastructure that shipped, and it is queryable by the workstream join rather than requiring a live handle. It is also the **first consumer** of the transcript store, whose own design doc lists "no recall surface" as the explicit next-step non-goal — this proposal fills exactly that gap.

**What we drop:** `message_agent` (one-way push into a live session). It needs a live cross-session channel Claude Code doesn't have, and it cuts against the copilot posture ("does not supervise, drive, or manage"). Copilot becomes **pull-only**: it reads status, it does not poke. If push is ever genuinely wanted, the native path is a durable **Routine** / scheduled trigger firing a prompt into the target session (§6.6) — heavy, cloud-bound, and out of scope for v1.

---

## 4. The build, in two artifacts

**The plugin (`claude/`) — mostly native:**
- `skills/copilot/SKILL.md` — the copilot loop (from `modes/copilot.md`), de-Pi'd, re-pointed at the MCP tools.
- `commands/copilot.md` *(optional)* — an explicit `/basecamp:copilot` entry (or rely on skill auto-surfacing).
- `src/basecamp/mcp/tools/workstreams.py` — `create_workstream`, `edit_workstream`, `list_workstreams`, `set_workstream_status`, `launch_workstream` (worktree provision + record attach), `workstream_status`.
- `src/basecamp/mcp/` resource — `basecamp://memory/cockpit` (+ dossier index); render from the memory dir.
- `src/basecamp/hooks/session.py` — SessionStart grows the `copilot/<slug>` branch: resolve workstream, inject brief as `additionalContext`, attach `session_id`.
- config — reuse `logseq.graph_dir` (or a new memory-dir key); no new launch flag.

**The daemon (`hub/claude/`) — the irreducible delta:** `WorkstreamsMixin` + contract bodies (v4) + routes + client methods + id/slug generation, per §3.4.

Everything else copilot touches — project context, related dirs, session registration, transcript ingestion, the fail-open hook chain, the MCP instructions router — **already exists** from Tier-0/1 and the transcript work.

---

## 5. Sequencing

Three slices, each independently shippable, ordered by value-per-cost:

- **C0 — Copilot as posture (pure native, zero daemon change).** The `copilot` skill + memory files + the `basecamp://memory/*` read resource + native worktrees. Delivers "an agent that orients you, makes the work choice-set legible, shapes workstreams as *dossiers*, and curates repo memory." Ships without touching the daemon. Highest value, lowest cost — this alone is a usable copilot.
- **C1 — Durable workstream records.** The daemon workstreams delta (§3.4) + the create/edit/list/status/launch MCP tools + the SessionStart brief-injection hook. Delivers durable, cross-session, versioned coordination and the worktree handoff.
- **C2 — Workstream status.** The `workstream_status` tool reading ingested transcripts (§3.5). Delivers "check on a launched workstream without interrupting it."

This maps onto the `claude/README.md` Tier-2 row but re-scopes its "cross-session messaging" to **cross-session reading**, which is both more native-adjacent and already built.

---

## 6. Native-capability audit (what the port relies on)

Confirmed against current Claude Code docs. Each is either used or explicitly declined.

1. **Skills / commands / subagents in a plugin** — all plugin-shippable, namespaced `plugin:name`, auto-surfaced by `description` (`disable-model-invocation: true` opts out). → the copilot **skill** + entry command.
2. **Output styles** — plugin-shippable (`output-styles/*.md`); `force-for-plugin: true` + `keep-coding-instructions: false` replaces the prompt wholesale, but is **plugin-wide, not launch-conditional**. → declined as default (skill is per-session); kept as an opt-in alternative.
3. **SessionStart hook** — plugin-shippable; can emit `hookSpecificOutput.additionalContext` (context injection) and gate on a `source` matcher (`startup` vs `resume`); **cannot inject a literal user turn**. → brief injection (as context; minor fidelity diff, verify per CLI version).
4. **PreToolUse deny** — `permissionDecision: "deny"` (or exit 2), matcher by tool name, plugin-shippable. → *available* to enforce "copilot doesn't Edit/Write," but **declined** per the compat doc's "don't port enforced modes"; the discipline stays prose.
5. **Git worktrees** — `claude -w`/`--worktree`, `EnterWorktree`/`ExitWorktree`, `worktree.baseRef`, `.claude/worktrees/`, `WorktreeCreate`/`WorktreeRemove` hooks, subagent `isolation: worktree`. → the staging worktree; a `WorktreeCreate` hook can preserve the `~/.worktrees/<org>/<name>/…` scheme if we want continuity (see §7).
6. **Durable scheduling & cross-session** — in-session cron is **ephemeral** (`CronCreate`/`/loop`, gone on exit); durable = **Routines** (`/schedule`, cloud, ≥1h) / desktop scheduled tasks (local, ≥1m). Independent sessions spawn via `claude -p` / the Agent SDK. **No native messaging between independent sessions** — they coordinate only through external channels (files, APIs, MCP). → validates status-via-daemon-read and pull-only copilot; a Routine is the (declined, heavy) push path.
7. **MCP `instructions` injection** — injected into the system prompt at session start; `claude/README.md` records an empirically-verified ~2KB truncation. Resources/tools surface natively as `mcp__basecamp__*`. → the memory resource + workstream tools; keep the instructions router lean, bulk in resources.
8. **Background subagents** — within-session only (shared session/transcript/permissions; `SendMessage` to message them; `isolation: worktree` for their own tree). **Not** independent user sessions. → confirms the workstream session is *not* a subagent (that would re-introduce the supervision copilot rejects); it is a separate `claude` session the daemon records observe.

---

## 7. Open decisions

Recommendations given; none block the C0 slice.

1. **Persona substrate** — **skill** (recommended: per-session, composable with native guidance) vs output style (`force-for-plugin`, wholesale, but plugin-wide).
2. **Records substrate** — **daemon-backed** (recommended: reuses the kept daemon, queryable cross-repo, additive multi-agent) vs **file-first** (dossier frontmatter *is* the record — maximally native, no daemon, but loses cross-repo listing and additive attachment). A defensible middle: C0 ships file-first (dossiers only), C1 adds the daemon index over them.
3. **Worktree scheme** — native `.claude/worktrees/<slug>` (simplest) vs keep `~/.worktrees/<org>/<name>/copilot/<slug>` via a `WorktreeCreate` hook (continuity with the basecamp per-repo setup hook). Recommend native default; hook only if the setup-hook coupling is wanted.
4. **Workstream session launch** — instruct-the-user (`cd <wt> && claude`, recommended, faithful to "copilot doesn't own it") vs auto-launch locally (`claude -w`) vs cloud Routine/trigger.
5. **Memory location** — `logseq.graph_dir` (Logseq continuity) vs repo-relative `.basecamp/memory/` (self-contained). Recommend keeping `logseq.graph_dir` for now; revisit if the Logseq dependency is being shed elsewhere.
6. **Brief-injection fidelity** — accept SessionStart `additionalContext` (context, not a user turn) after version-verifying it, or fall back to a first-turn skill nudge.

---

## 8. Risks & caveats

- **Web sandbox.** Worktree provisioning and local session launch no-op on Claude Code for web (no host git worktree lifecycle / tmux). Records, memory, and status still work (daemon + files + MCP). A known Tier-2 constraint, not new.
- **MCP instructions cap.** ~2KB, truncated — keep the router a pointer, never the payload.
- **No literal user-turn injection.** The brief lands as context; verify the exact SessionStart output contract against the pinned CLI version.
- **No native cross-session push.** Status is pull-only by design; a push channel would require Routines and is out of scope.
- **Daemon protocol bump.** 3 → 4 respawns stale daemons via the health gate — the existing, tested pattern; keep DDL additive (the store has no `ALTER` migration).
- **Posture is not enforced.** "Copilot stages, doesn't implement" is prose, not a guard. If enforcement is ever required, §6.4's PreToolUse deny is the lever — but the compat doc's position is that it shouldn't be.

---

## 9. In one line

Copilot decomposes into five layers; **three land on pure native Claude Code** (a skill for the posture, files + one MCP resource for memory, native worktrees + the existing SessionStart hook for staging), and **two form an irreducible daemon core** (durable workstream *records* as MCP tools over the already-kept Claude daemon, and workstream *status* as a read over the already-built transcript ingestion) — shedding the entire Pi apparatus of a locked mode, a full-prompt replacement, a Herdr pane, a WebSocket dispatch mesh, and cross-session push, none of which survive contact with what Claude Code already does.
