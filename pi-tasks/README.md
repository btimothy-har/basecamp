# pi-tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, `/plan` command, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `annotate_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `/plan` command with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff
- **Workstream launch**: `launch_workstream` and `list_workstream_launches` (see below)
- **Workflow skills**: `gather`, `planning` SKILL.md content (`agents` skill moved to pi-swarm)

The sync in-process agent tool has been removed in the cutover. pi-swarm/extension now provides the sole agent tool (daemon-backed `dispatch_agent`/`wait_for_agent`/`list_agents`).

## Workstream launch

The handoff is manual by design, so a workstream runs as a normal user-facing pi session tied to the repo rather than a headless worker.

`launch_workstream` stages exactly one workstream from a dossier-backed brief: it provisions a single execution worktree via `getOrCreateWorktree` (without touching or activating the copilot session's own worktree/cwd/env), runs configured setup for a newly created worktree, opens a Herdr pane on the worktree (best-effort), and records the workstream under a short human-typeable **id**. The worktree gets a generic three-word name (`copilot/<three-words>`) and the id is those same three words, so the id is derivable from the worktree directory; the initial branch stays work-derived (`<user-prefix>/<work-slug>`, e.g. `bt/…`). It does not dispatch an agent. Herdr opening is explicit to this tool — ordinary worktree activation never mutates Herdr. The pane is opened first; the user runs `pi --workstream` (bare, id inferred from the worktree) once the pane is ready.

Schema is brief-centered and minimal: required `source.dossierPath`, `workstream.label`, `workstream.brief`; optional `source.repoPagePath`, `workstream.constraints`, `workstream.worktreeSlug` (derives the initial `bt/` branch name, not the worktree label). The brief is intentionally stretchable — it can describe a broad workstream to decompose or a specific agreed slice to execute.

The user then runs `pi --workstream` in the new pane, which infers the id from the current `copilot/<three-words>` worktree. If no pane opens, they can `cd <worktree-path> && pi --workstream` manually. That launch command loads the workstream record by matching the active worktree label, injects the built brief as the opening prompt, and stamps the running session's public daemon handle onto the record so copilot can reach it. The brief tells the agent it owns its worktree, may coordinate sub-agents, may implement within the worktree when the brief calls for it, must not write Logseq, and must not push, open PRs, or merge unless asked.

`list_workstream_launches` is the read companion: it lists workstream records for the current repo (optionally filtered by `dossierPath` or label substring) so a caller can route to an existing workstream's id/handle instead of staging a duplicate.

The launch index (`~/.pi/basecamp/workstream-launches/launch-index.json`) is an operational receipt only — which workstream was staged for which dossier and brief, in which worktree, under which id, and (once `pi --workstream` launches) which agent handle, plus setup/Herdr/launch status. It is not durable workstream state: priority, decisions, blockers, and done signals live in Logseq. No transcripts or dispatch logs are stored. Duplicates are refused: a matching non-failed record (same repo + dossier + label) is reused, and a failed record is superseded on retry. Generic worktree names are generated to avoid collisions with existing launch ids and worktree labels (regenerating on the rare clash); if the work-derived `bt/` branch is already checked out in another worktree, staging fails and asks for a distinct `worktreeSlug`.

`launch_workstream` and `plan()` are siblings. `plan()` remains the in-session implementation handoff for the current (parent) session; `launch_workstream` stages a separate user-facing workstream the user starts with `pi --workstream` from inside the worktree. Copilot pulls current state from a started workstream on demand via the pi-swarm known-handle `ask_agent`/`message_agent` path and curates the durable parts into Logseq itself. The stamped handle is a contact address only: it does not make the workstream listable, awaitable, retaskable, or dispatchable from copilot.

## Functional smoke cleanup

For manual workstream smoke tests, use an obviously disposable label such as `functional-known-handle-smoke` and verify only the behavior under test: staging, `pi --workstream` handle stamping, known-handle `message_agent`, and known-handle `ask_agent` when the session is forkable.

Cleanup is manual by design:

1. Close the Herdr pane opened for the smoke workstream.
2. Remove the smoke worktree and branch using the normal reviewed git/worktree workflow for this repo.
3. If the smoke launch receipt is clearly identified, remove only that record from `~/.pi/basecamp/workstream-launches/launch-index.json`.

Do not add cleanup automation casually. Worktree deletion, branch deletion, and launch-index mutation are destructive enough to need separate design.

## Dependencies

- **pi-core** (hard peer dep): TasksAccess type contract + registry, agent-mode, session state, workspace state + worktree operations, skill-tracker, catalog, model-aliases

## Type contracts

`TasksAccess`, `TaskStatus`, `Task`, `ReviewState`, `GoalCycle` are owned by pi-core (`pi-core/platform/tasks-access.ts`). Pi-tasks implements `TasksAccess` and registers it into pi-core's registry. Companion and swarm observe via `getTasksAccess()` (returns null if pi-tasks not installed).

## Installation

```bash
pi install /path/to/pi-tasks
```

Installed automatically by `install.py`.
