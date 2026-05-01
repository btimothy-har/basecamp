---
name: planning
description: "Invoke before formalising execution after discovery. Triggers: 'plan this', 'let's plan', multi-step implementation or refactoring, architectural decisions, substantial analysis or validation. Do NOT use plan() to start exploration."
---

# Planning

## What Planning Is

A plan is an evidence-backed agreement, not a task list with a header. Before calling `plan()`, you and the user should share an understanding of what exists, what problem is being solved and why, which approach is being chosen, which trade-offs are accepted, what done looks like, and what is out of scope. Tasks come from that agreement; they are not the plan itself.

Planning turns discovery into approved execution. The `plan()` tool is for approving the next consequential work phase — implementation, validation, substantial analysis, or another execution workflow — once the context and approach are understood.

## Exploration vs. Execution

Exploration is non-mutative. Read code, inspect docs, search history, run safe read-only checks, and use subagents when useful. Do not use `plan()` to authorise discovery itself; use it when discovery has produced enough context to propose a bounded execution path.

Prototypes, spikes, repo edits, expensive validation runs, and substantial analysis execution require an approved plan and handoff first.

---

## When to Use `plan()`

Use `plan()` when the approach matters and the next work phase needs explicit user approval before execution:

- Multi-step implementation or refactoring
- Architectural or product decisions with meaningful trade-offs
- Substantial data analysis or research execution after you have validated sources and methodology through exploration
- Validation plans that run meaningful checks, commands, queries, or review workflows
- Work that needs clear success criteria, scope boundaries, or execution handoff

Do not use `plan()` to begin exploration. If you do not yet understand the current system, constraints, options, or success criteria, keep investigating and discussing. For simple, obvious work, use `update_goal` → `create_tasks` instead.

---

## How to Plan

### Build Context

Investigate before formalising. Read the relevant code, docs, configuration, schemas, prior decisions, or logs needed to understand the problem. Use the `gather` skill when user requirements need clarification, and ask only for gaps you cannot resolve from available context.

You are ready to move toward a plan when you can explain what exists, what is changing, why it matters, and what constraints shape the solution without guessing.

### Shape the Approach

Planning is collaborative design work. Surface viable approaches with trade-offs, recommend one, and explain why it fits better than the alternatives. Challenge scope when the simpler path would satisfy the goal.

If the user wants to skip to `plan()` before the approach is agreed, push back: formalising before shared understanding creates a task list, not a plan.

Good approach discussion answers:
- What are we solving, and why now?
- What options were considered?
- Which option are we choosing, and why?
- What trade-offs or risks are we accepting?
- What is explicitly out of scope?

### Agree on Scope

Before calling `plan()`, align on the boundaries that prevent drift. Decide what the work includes, what it excludes, what success looks like, and which unresolved questions matter enough to resolve now. Do not hide unresolved decisions inside tasks; if a task depends on a decision that has not been made, make the decision before formalising.

### Formalise with `plan()`

Call `plan()` only after discovery and discussion have converged. The plan sections should reflect the agreed direction, not introduce new thinking.

```
plan({
  goal:        // one sentence — what are we achieving
  context:     // what exists, constraints, triggers
  design:      // the agreed approach — patterns, trade-offs, decisions
  success:     // plan-level success criteria — concrete and verifiable
  boundaries:  // what's out of scope — prevents drift
  tasks:       // ordered steps, each with label + description + criteria
  worktreeSlug: "handoff-labels" // optional hidden metadata for implementation handoff
})
```

For implementation plans, include `worktreeSlug` as hidden metadata: a short semantic kebab-case slug with no session prefix, e.g. `handoff-labels`. Omit it for analysis-only plans. This is not a user-reviewed plan section; the user sees the worktree selector later and can override the final label there.

The user reviews via an interactive overlay. They may:
- **Approve** sections/tasks
- **Revise** — flag for changes
- **Leave feedback** — notes on specific items

If feedback is returned, address it and re-submit. Unchanged approved sections keep their status.

Once every item is approved and submitted, follow the plan result. Implementation plans ask for supervisor vs IC/executor posture; if the approved result includes a scheduled handoff, do not begin implementation in the current turn. End the turn and let Basecamp start the fresh handoff turn so the selected posture prompt is loaded. Analysis-mode plans stay in analysis mode; begin the approved analysis tasks without supervisor/executor handoff.

---

## What Good Looks Like

A good plan is specific enough that another agent could execute without reopening the whole discovery conversation.

- **Goal** — one clear outcome, not a vague improvement area
- **Context** — evidence from the actual system, source data, workflow, or user need
- **Design** — the chosen approach and why it wins over alternatives
- **Success** — concrete, verifiable criteria
- **Boundaries** — explicit exclusions that prevent drift
- **Tasks** — ordered execution chunks that follow from the agreed approach

The design section is where the thinking lives. Do not just describe what will be built or run; explain the trade-offs and decisions that make this plan coherent.

---

## Anti-Patterns

A `plan()` call is **not**:

- A premature task list assembled before the approach is agreed
- A generic checklist of default implementation steps
- A substitute for discovery — open questions belong in exploration or discussion
- A place to defer unresolved decisions that would change the approach
- A request for permission to investigate the problem
- A way to make simple, obvious work feel more formal than it is

---

## Section Guidance

### Goal

One sentence. Specific enough that you'd know when it's done.

> Migrate user authentication from server-side sessions to JWT with refresh token rotation

Not "improve auth" or "refactor the auth system."

### Context

Prose. Supports the goal — why this work matters, what exists today, what triggered it, relevant constraints. The goal says *what*, context says *why now*. Don't restate the goal.

### Design

Prose. This is the most important section — it's where the thinking lives. Explain the approach and **why** this approach over alternatives. Don't just describe what you'll build — explain the trade-offs and decisions.

### Success

Bullet list. Concrete, verifiable criteria. Each item should be independently checkable.

```
- p95 latency under 200ms
- Cache hit rate above 80% for product detail endpoints
- No stale data beyond TTL window
- PostgreSQL query volume reduced by at least 60%
```

Not "it works" or "tests pass."

### Boundaries

Bullet list. What's explicitly out of scope. Each item prevents a specific kind of drift.

```
- No cache invalidation on writes — TTL handles staleness
- No cache warming on deploy
- No distributed cache coordination
- Redis failure = fall through to PostgreSQL
```

Not "keep it simple" or "no gold-plating."

### Tasks

Ordered list. Smallest meaningful units of work — logical chunks, not individual file edits. Each task needs a label, description (what and why), and criteria (what done looks like for this task). Tasks should follow directly from the agreed approach; if a task requires a decision that has not been made, make that decision before formalising.
