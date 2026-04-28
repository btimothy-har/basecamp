---
name: planning
description: "Invoke for structured planning before execution. Triggers: 'plan this', 'let's plan', architectural decisions, multi-step features, refactors. Do NOT skip to plan() — explore and discuss first."
---

# Planning

## Purpose

Turn a user's intent into a structured, reviewed plan via the `plan()` tool. Planning is a **three-phase process** — exploration, discussion, then formalisation. Do not jump straight to `plan()`.

---

## Process

### Phase 1: Explore

Invoke the `gather` skill. Investigate the problem space autonomously — read code, check docs, understand what exists. Then engage the user to fill gaps.

**Push back if the request is vague.** Don't plan what you don't understand. If the user says "plan the auth refactor" but you don't know the current auth system, investigate first.

**Exit criteria:** You can explain what exists, what's changing, and why — without guessing.

### Phase 2: Discuss

Align on approach **before** formalising. This is a conversation, not a presentation.

- Surface 2-3 approaches with trade-offs
- Recommend one and explain why
- Challenge scope — apply YAGNI, suggest phasing
- Agree on boundaries: what's in, what's out

**Push back if the user wants to skip discussion.** A plan without shared understanding is just a task list with extra steps.

**Exit criteria:** Both you and the user agree on what to build, how, and what's explicitly out of scope.

### Phase 3: Formalise

Now call `plan()`. The sections should reflect what was discussed — not new thinking.

```
plan({
  goal:       // one sentence — what are we achieving
  context:    // what exists, constraints, triggers
  design:     // the agreed approach — patterns, trade-offs, decisions
  success:    // what done looks like — concrete and verifiable
  boundaries: // what's out of scope — prevents drift
  tasks:      // ordered steps, each with label + description + criteria
})
```

The user reviews via an interactive overlay. They may:
- **Approve** sections/tasks
- **Revise** — flag for changes
- **Leave feedback** — notes on specific items

If feedback is returned, address it and re-submit. Unchanged approved sections keep their status.

Once every item is approved and submitted, follow the plan result. Implementation plans ask the user whether to execute as supervisor or IC/executor; if the approved result includes an implementation mode, begin executing in that posture. Analysis-mode plans stay in analysis mode; begin the approved analysis tasks without supervisor/executor handoff.

---

## When NOT to plan

Not everything needs `plan()`. Use `update_goal` → `create_tasks` for:
- Bug fixes with obvious cause
- Config changes
- One-shot tasks
- Anything where the approach is self-evident

The user chooses when to plan (via `/plan`). Don't suggest planning for simple work.

---

## Section guidance

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

Ordered list. Smallest meaningful units of work — logical chunks, not individual file edits. Each task needs a label, description (what and why), and criteria (what done looks like for this task).
