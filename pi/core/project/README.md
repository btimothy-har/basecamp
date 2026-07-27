# project

The active project's working environment — *which project the session is in, its context, and where the agent works*. A `pi/core/project/` subsystem registered by `registerCore` (via `registerProject`). `basecamp.workspace` (`src/basecamp/workspace/`) is the Python side: per-repo worktree-setup environments + interactive CLI menus.

## What it does

- **`config.ts`** — resolve the project from the `projects` section of `~/.pi/basecamp/config.json` (by repo root → name, `additionalDirs`, `workingStyle`, context; context overrides live in `~/.pi/basecamp/context/`), hold the `ProjectState` cell, and register the `session_start` resolve + `BASECAMP_PROJECT`.
- **`context.ts`** — discover ancestor `AGENTS.md`/`CLAUDE.md` context files.
- **`injection.ts`** — a `tool_result` hook that injects nested `AGENTS.md`/`CLAUDE.md` just-in-time as the agent enters a subtree that has its own.
- **`logseq.ts`** — the copilot repo-memory (Logseq) context block, and the copilot-gated registration of the skill that documents it.
- **`workspace/`** — the active working environment (below).

### `workspace/` — the worktree runtime

- **`runtime.ts`** — `WorkspaceRuntimeService`: active-worktree state machine, effective cwd, `BASECAMP_*` env, cwd provider (survives `/reload`).
- **`state.ts`** — `WorkspaceState` types + accessors (`getWorkspaceState`, `getWorkspaceEffectiveCwd`, `onWorkspaceChange`, `activate`/`attachWorkspaceWorktree`, …) + the allowed-roots registry. Thin reads over the runtime — no pluggable seam.
- **`session.ts`** — `session_start` bootstrap: init, legacy-worktree migration, restore, `.env`, the `--worktree-dir`/`--read-only`/`--unsafe-edit` flags, the Logseq allowed-root.
- **`guards.ts` · `unsafe-edit.ts`** — edit guards: block writes to the protected checkout, retarget paths into the active worktree.
- **`command.ts`** (`/worktree`, primary only) · **`affinity.ts`** (session↔worktree bridge) · **`setup.ts`** (per-repo worktree-setup command).

## Registration & ordering

`registerProject` sequences **workspace bootstrap → project resolve → context injection** in one function, so project's `session_start` (which reads workspace state) runs after workspace init without a cross-module trick. The allowed-roots registry is internal — `config.ts` registers `projects`, `workspace/session.ts` registers `logseq`.

## Dependencies

- **`#core/git/*`** — the worktree runtime consumes the git mechanics. Otherwise `#core/*` only (host, session state, global-registry). Read across the extension via `#core/project/workspace/state.ts` (workspace) and `#core/project/config.ts` (project state).

## Repo copilot Logseq memory

Copilot is a locked, launch-only mode entered with `pi --copilot`: it is immutable (shift+tab can neither enter nor leave it) and the `plan()` handoff is disabled in it. Copilot mode can use a configured Logseq graph as durable repo memory. Configure the graph manually in `~/.pi/basecamp/config.json`:

```json
{
	"logseq": {
		"graph_dir": "~/logseq/main"
	}
}
```

The path must exist and point at the Logseq graph root. Basecamp expects normal Logseq page files under the graph's `pages/` directory. Basecamp registers the configured graph as an allowed root (via `workspace/session.ts`) so normal file tools can read/update these Markdown files from repo sessions. There are no custom Logseq tools, no background sync, and no automatic graph scan.

### Three artifacts

Repo memory is **durable context vs. live state**: a dossier holds what stays true; a journal holds what happened that day. Three artifacts, three write modes, three authorities:

| Artifact | Role | Write mode | Authority |
|---|---|---|---|
| `journals/YYYY_MM_DD.md` | What happened today | Append | Source of truth for activity |
| `pages/work__<org>__<repo>__<slug>.md` | Durable context | Edit, rarely | Source of truth for durable framing |
| `pages/repo__<org>__<repo>.md` | Repo anchor | Authored, sparse | Not a work record |

Page names are flat (`__`-joined) and filename-safe: `logseq.ts` depends on pagename == filename, which is also what makes the dossier glob work.

**Dossier schema** — page properties `type:: work-dossier` and `repo:: [[repo__<org>__<repo>]]`, then sections `## Objective`, `## Context`, `## Decisions`. Deliberately no `status::`, `priority::`, `updated::`, `workstreams::`, and no `## Done signal` — status is the daemon's job (below), and the done signal is one of the workstream record's fields.

**Cockpit** — an anchor page holding only what would be wrong to commit to the repo: standing priorities, external dependencies, people. Not an index, not a status board. The rule doubles as a smell test: if the cockpit starts reading like `AGENTS.md`, the content belongs in the repo. It earns its place as the anchor journal blocks nest under, even when nearly empty.

**Journal nesting** — repo-first, because the graph is global and a top-level heading would collide between repos on the same day:

```markdown
- ## [[repo__btimothy-har__basecamp]]
	- ### [[work__btimothy-har__basecamp__quiet-heron-drift]] · `gentle-marten-tide`
		- Reframed around journals; dropped status/priority/updated.
		- CI red on #318 — root cause is the boundary check.
	- ### [[work__btimothy-har__basecamp__third-slug]]
		- Shaped scope; no workstream staged yet.
```

The dossier reference leads and the workstream slug qualifies it. Slug-first was rejected because a dossier exists before any workstream is staged and one dossier can back several workstreams — which reads correctly as sibling blocks sharing a dossier ref. Keeping the dossier ref as the linking spine is what makes Logseq's linked references catch the whole live timeline.

### Why this cannot drift

Journal blocks reference `[[work__…]]`, so opening a dossier shows durable context on top and the whole live timeline underneath, assembled by Logseq's linked references and never stored on the page. A derived timeline cannot drift because there is no second copy.

### Authority split

The daemon owns workstream lifecycle (`CHECK(status IN ('open','closed'))` in `src/basecamp/hub/store/workstreams/schema.py`, plus the `set_workstream_status` tool). Journals therefore record events and never status: a journal page is day-specific, so writing "closed" freezes a fact that can change tomorrow, and a workstream can be revived.

### Read bound

The context block sanctions reading the last **14 days** of journals plus a dossier's linked references, and still forbids scanning the whole graph. The bound is load-bearing because there is no cached choice set — copilot rebuilds "what is active/waiting/blocked" from recent journals each session.

### Guidance placement

The page schema and write mechanics live in a copilot-only skill named `copilot` at `pi/core/project/skills/copilot/SKILL.md`, registered through a `resources_discover` handler gated on `isCopilotLaunch()`. The predicate is read inside the handler, so each discovery re-evaluates it rather than capturing it at registration. It is not in the manifest `pi.skills` array because that route is unconditional. `pi/system-prompt/defaults/modes/copilot.md` keeps only the charter plus a pointer to the skill.

A write rule is duplicated into the mode when a page would be actively wrong without it, because the skill is model-invoked rather than auto-loaded and a session can reach a write without loading it. Two qualify: memory is written for the user rather than as the agent's research notes, and nothing unverified reaches the page. Everything else — the page schema, the operational write rules, and the before/after contrast — lives only in the skill.

### Workstream interaction

Logseq is the durable memory; workstreams are the user-facing execution surfaces. When copilot stages a workstream (via `launch_workstream`, owned by the swarm context) it provisions a `copilot/<slug>` worktree + Herdr pane and creates the workstream in the daemon; the user runs `pi --workstream` in that pane (bare form infers the slug from the worktree). Workstream agents never write Logseq and do not push updates to copilot.

### Rejected alternatives

- **Cockpit `## Now` rollup cache** — reintroduces a second writer of state, the exact failure this design removes.
- **Cockpit `## Index` section** — the dossier glob already serves copilot and a Logseq query serves the human; it would be a third copy.
- **Dossier `workstreams::` property** — the journal records launches as events and `list_workstreams --dossierPath` already answers it for copilot.
- **A separate `pi/repo-memory/` domain owning `logseq.ts` and the skill** — `pi/system-prompt/*.ts` imports `#core/*` exclusively, so moving the context builder out would make the prompt assembler depend on a feature domain for the first time. `pi/core/swarm/skills/agents/` is precedent for a skill living in core beside the capability it documents.
- **Native Logseq namespaces (`repo/org/name`) instead of flat `__` names** — out of scope; it would break every existing page. Flat names keep page names identical to filenames, which is what makes the glob work.
- **Writing `title::`** — never do it. It is Logseq's filename-to-display mapping for names with reserved characters and has known drift edge cases; our page names are already filename-safe and `logseq.ts` depends on pagename == filename.
- **Naming the skill `repo-memory`** — it describes the content better, but the skill is reachable only from copilot sessions and `copilot` is what the user reaches for. The usual rule that a capability is named for what it is, not for who may call it, is deliberately not applied here.
