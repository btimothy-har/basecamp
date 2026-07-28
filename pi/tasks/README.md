# tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, the `plan()` handoff, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `plan()` tool with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff, and `/show-plan` to view the current plan (the `plan()` tool is hard-blocked in copilot sessions)
- **Continuation guard**: judges each stop and nudges the agent onward when it stopped prematurely (see below)
- **Workflow skills**: `gather`, `planning` SKILL.md content (the `agents` skill lives in the swarm context)

> **Note**: The workstream domain (`launch_workstream`, `list_workstreams`, `set_workstream_status`, and the `pi --workstream` startup flag) is its own domain (`pi/workstreams/`), persisted in the daemon's SQLite store. The agent tools (`dispatch_agent`/`wait_for_agent`/`list_agents`) belong to the `#core/swarm` primitive.

## Functional smoke cleanup

For manual workstream smoke tests, use an obviously disposable label such as `functional-known-handle-smoke` and verify only the behavior under test: staging, `pi --workstream` agent attachment, known-handle `message_agent`, and known-handle `ask_agent` when the session is forkable.

Cleanup is manual by design:

1. Close the Herdr pane opened for the smoke workstream.
2. Remove the smoke worktree and branch using the normal reviewed git/worktree workflow for this repo.
3. If the smoke workstream record is clearly identified, remove it from the daemon's SQLite store or close it with `set_workstream_status`.

Do not add cleanup automation casually. Worktree deletion, branch deletion, and workstream-record mutation are destructive enough to need separate design.

## Continuation guard

The domain owns the stop protocol — `escalate` when the user is needed, a work summary when the work is done — so it also owns catching stops that honor neither. `lifecycle/continuation/` hooks `agent_end` and, when a stop looks premature, queues one hidden `followUp`, which makes Pi continue the run.

There is deliberately no tool argument for ending the loop. `complete_task` once took `stop_work`, which returned `terminate: true`; the guard honoured it as a precondition and the suppression never held — it was cleared per `agent_end`, so any peer `followUp` (the dirty-worktree reminder, routinely) produced a second stop with the flag already reset. `terminate` was also the main way a run ended with no assistant text, which let a nudged continuation record an empty deliverable. The rubric judges every stop instead, and recognises a finished agent through veto D.

**Two layers, and the split is load-bearing.** `policy.ts` answers only *may this hook act at all*; it never judges the stop. `judge.ts` + `rubric.ts` are the sole authority on whether a stop was premature.

Mechanical preconditions (no model call when any holds), in the order they are reported:

| Block | Meaning |
|-------|---------|
| `provider_error` | The model call itself failed, so there is no agent judgment to nudge |
| `plan_handoff_active` | `plan()` already owns a restart for this stop |
| `pending_user_messages` | The user has already spoken; their message wins |
| `cap_reached` | The safety bound |
| `aborted` | The run was cancelled while the judge was still deciding |

`provider_error` substitutes for Pi's `willRetry`, which extensions never receive — Pi attaches it to its internal session event only, and derives it from the last assistant message being a retryable error, so the guard reads that same message. It is **not** rubric category E, which is about an agent abandoning work after a *tool* failure.

`aborted` and a second `pending_user_messages` check are re-read *after* the judge returns, because both go stale across that await — and the window is exactly when a user aborts or types, since Pi drains its queues immediately before `agent_end`. Pi resumes on any queued message without checking for an abort, so a nudge sent after an ESC would restart the run the user just cancelled. The judge call itself carries a deadline combined with the run signal: it holds run settlement open while in flight, so an unbounded call would wedge every stop with no way out.

The rubric, judged by the `fast` model in one forced tool call:

| | Category | Verdict |
|---|----------|---------|
| **Q** | Asked — the final message asks the user anything, including a question whose answer looks obvious | hold |
| **D** | Delivered — the goal is satisfied, or findings/a plan were presented for review | hold |
| **H** | Held — waiting on a human action or external event it cannot progress | hold |
| **I** | Intent — the message states or implies a next action that was not performed | nudge |
| **R** | Remaining — goal or task state shows work left, and the message neither asks nor claims completion | nudge |
| **E** | Error — stopped at an unresolved error without recovering or delivering a conclusion | nudge |

Uncertainty holds. Goal and task state are **evidence inside category R, not a gate**: an open task does not prove a premature stop (an agent may legitimately need input mid-task), and gating on open tasks would be escapable by marking them complete — in a feature whose whole purpose is catching agents that stop when they shouldn't.

`retrigger` and the category's polarity are redundant on purpose: the parser rejects a verdict whose `retrigger` disagrees with its category, so model confusion becomes no action rather than the wrong action. One `verdictSchema` factory builds both the tool schema the model answers against and the schema the parser validates, so the offered categories and the accepted ones cannot drift.

**Fail open.** No `fast` alias, no verdict, a malformed or self-contradicting response, a judge timeout, or any thrown error all mean *no nudge*. This inverts the bash reviewer's fail-closed posture on purpose: a wrong stop costs the user a keystroke, while a wrong continue burns a whole agent run.

The guard needs a `fast` model alias and is inert without one. That is a dependency, not a control: the same alias backs the bash reviewer, which is fail-*closed*, so removing it would route every gated command to a confirmation prompt and deny them outright in subagents. There is no off switch.

**Subagents diverge.** A dispatched agent has no user, so veto Q is withheld from the rubric text, the tool schema, *and* the parser (`offeredCategories` is the one source of truth): a question there is unanswerable, and stopping on one wastes the run. Its nudge tells it to decide and proceed, or report the blocker as its deliverable — and to restate its result in full, because a dispatched run's recorded result is whatever its final message says, so a continuation that omits the deliverable discards it.

**The nudge is two static texts**, one per context. The judge's `reason` never reaches an agent: routed through a `<system-reminder>`, which Pi converts to a user message, model-authored text would launder whatever the judge read — file contents, tool output, a peer's message — into apparent harness instruction. The reason stays in the audit trail.

Every decision, nudge and hold alike, is recorded via `pi.appendEntry("continuation-guard", …)` with its category, so a misfiring category is diagnosable. Nudge chains are capped at 2, reset only by a genuine user message — the nudge is a custom message and so cannot reset its own counter. Copilot sessions are excluded.

## Structure

One feature, organized by function (not sub-features):

- **`schemas/`** — the shared data models (`task.ts`, `plan.ts`); the import-nothing leaf.
- **`lifecycle/`** — the durable goal/task state machine: runtime, goal-cycle operations, persistence, and widget, plus `continuation/` (the stop guard: `policy.ts`, `judge.ts`, `rubric.ts`, `messages.ts`, wired by `index.ts`). The guard receives `planHandoffActive` as a callback rather than importing `PlanAccess`, so this layer never depends upward on `tools/`.
- **`workflows/`** — the stateless `plan()` procedures: `draft.ts`, `review/`, `handoff/` (incl. `runHandoff`).
- **`tools/`** — the thin agent-facing surface: `task-tools.ts`, `plan-tool.ts`, `commands.ts`, `guards.ts`, `render.ts`. Wired by the composition root; depends downward on the layers below.

## Dependencies

- **core** (`#core/*`): agent-mode (+ copilot), session state, workspace service + worktree setup, skill-tracker, host paths/config, model-alias resolution (the continuation guard's `fast` judge), errors

## Type contracts

`TaskStatus`, `Task`, `ReviewState`, `TasksState`, `GoalCycle`, and the plan models (`PlanDraft`, …) live in `pi/tasks/schemas/`. Types needed outside the domain are exported through `#tasks/index.ts`; mutation remains behind the task tools and lifecycle runtime.
