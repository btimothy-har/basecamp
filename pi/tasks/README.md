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

The domain owns the stop protocol — `escalate` when the user is needed, `complete_task({stop_work:true})` when the work is done — so it also owns catching stops that honor neither. `lifecycle/continuation/` hooks `agent_end` and, when a stop looks premature, queues one hidden `followUp`, which makes Pi continue the run.

**Two layers, and the split is load-bearing.** `policy.ts` answers only *may this hook act at all*; it never judges the stop. `judge.ts` + `rubric.ts` are the sole authority on whether a stop was premature.

Mechanical preconditions (no model call when any holds), in the order they are reported:

| Block | Meaning |
|-------|---------|
| `provider_error` | The model call itself failed, so there is no agent judgment to nudge |
| `plan_handoff_active` | `plan()` already owns a restart for this stop |
| `stop_work` | The agent invoked the documented loop-termination signal |
| `pending_user_messages` | The user has already spoken; their message wins |
| `cap_reached` | The safety bound |

`provider_error` substitutes for Pi's `willRetry`, which extensions never receive — Pi attaches it to its internal session event only, and derives it from the last assistant message being a retryable error, so the guard reads that same message. It is **not** rubric category E, which is about an agent abandoning work after a *tool* failure.

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

**Fail open.** No `fast` alias, no verdict, a malformed response, or any thrown error all mean *no nudge*. This inverts the bash reviewer's fail-closed posture on purpose: a wrong stop costs the user a keystroke, while a wrong continue burns a whole agent run. Removing the `fast` alias disables the guard entirely — that is the off-switch, in place of a config surface.

**Subagents diverge.** A dispatched agent has no user, so veto Q is withheld from both the rubric text and the tool schema (`offeredCategories`, one source of truth so the two cannot drift): a question there is unanswerable, and stopping on one wastes the run. Its nudge tells it to decide and proceed, or report the blocker as its deliverable.

Every decision, nudge and hold alike, is recorded via `pi.appendEntry("continuation-guard", …)` with its category, so a misfiring category is diagnosable. Nudge chains are capped at 2, reset only by a genuine user message — the nudge is a custom message and so cannot reset its own counter. Copilot sessions are excluded.

## Structure

One feature, organized by function (not sub-features):

- **`schemas/`** — the shared data models (`task.ts`, `plan.ts`); the import-nothing leaf.
- **`lifecycle/`** — the durable goal/task state machine: runtime, goal-cycle operations, persistence, and widget, plus `continuation/` (the stop guard: `policy.ts`, `judge.ts`, `rubric.ts`, `messages.ts`, wired by `index.ts`). The guard receives `planHandoffActive` as a callback rather than importing `PlanAccess`, so this layer never depends upward on `tools/`.
- **`workflows/`** — the stateless `plan()` procedures: `draft.ts`, `review/`, `handoff/` (incl. `runHandoff`).
- **`tools/`** — the thin agent-facing surface: `task-tools.ts`, `plan-tool.ts`, `commands.ts`, `guards.ts`, `render.ts`. Wired by the composition root; depends downward on the layers below.

## Dependencies

- **core** (`#core/*`): agent-mode (+ copilot), session state, workspace service + worktree setup, skill-tracker, host paths/config

## Type contracts

`TaskStatus`, `Task`, `ReviewState`, `TasksState`, `GoalCycle`, and the plan models (`PlanDraft`, …) live in `pi/tasks/schemas/`. Types needed outside the domain are exported through `#tasks/index.ts`; mutation remains behind the task tools and lifecycle runtime.
