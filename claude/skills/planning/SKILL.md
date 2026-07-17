---
name: planning
description: "Planning guidance for formalising execution after discovery. Triggers: 'plan this', 'let's plan', multi-step implementation or refactoring, architectural decisions, and substantial analysis or validation. Plan mode approves an approach — it is not for starting exploration."
---

# Planning

## What Planning Is

A plan is an evidence-backed agreement, not a task list with a header. Before you present a plan for approval, you and the user should share an understanding of what exists, what problem is being solved and why, which approach is being chosen, which trade-offs are accepted, what done looks like, and what is out of scope. Tasks come from that agreement; they are not the plan itself.

Planning turns discovery into approved execution. Plan mode is for approving the next consequential work phase — implementation, validation, substantial analysis, or another execution workflow — once the context and approach are understood.

## Exploration vs. Execution

Exploration is non-mutative. Read code, inspect docs, search history, run safe read-only checks, and use subagents when useful. Do not present a plan to authorise discovery itself; present one when discovery has produced enough context to propose a bounded execution path.

During exploration, treat early ideas as disposable strawmen: compare them against actual constraints, look for evidence that would make them a poor fit, and revise or discard them before converging. The goal is not to prolong debate; it is to test assumptions and alternatives enough that the final recommendation is justified.

Prototypes, spikes, repo edits, expensive validation runs, and substantial analysis execution require an approved plan first.

---

## When to Present a Plan

Present a plan when the approach matters and the next work phase needs explicit user approval before execution:

- Multi-step implementation or refactoring
- Architectural or product decisions with meaningful trade-offs
- Substantial data analysis or research execution after you have validated sources and methodology through exploration
- Validation plans that run meaningful checks, commands, queries, or review workflows
- Work that needs clear success criteria, scope boundaries, or execution handoff

Do not present a plan to begin exploration. If you do not yet understand the current system, constraints, options, success criteria, invalidated alternatives, surviving assumptions, or remaining uncertainty, keep investigating and discussing. For simple, obvious work, skip formal planning — state the goal and track the steps with your todo list.

---

## How to Plan

### Build Context

Investigate before formalising. Read the relevant code, docs, configuration, schemas, prior decisions, or logs needed to understand the problem. Apply the `gather` skill when user requirements need clarification, and ask only for gaps you cannot resolve from available context.

You are ready to move toward a plan when you can explain what exists, what is changing, why it matters, and what constraints shape the solution from evidence rather than untested assumptions.

### Shape the Approach

Planning is collaborative design work. Surface viable approaches with trade-offs, test them enough to justify convergence, then recommend one and explain why it is the strongest survivor. Challenge scope when the simpler path would satisfy the goal.

Before recommending convergence, test the leading option against disconfirming evidence and compare it with plausible alternatives. It is acceptable to sketch disposable strawmen, then retire them when the evidence or constraints show they do not fit. Preserve the useful learning: which alternatives were invalidated, which assumptions survived, what uncertainty remains, and why the recommended plan survived the comparison.

If the user wants to skip straight to a plan before the approach is agreed, push back: formalising before shared understanding creates a task list, not a plan.

Good approach discussion answers:
- What are we solving, and why now?
- What options were considered?
- Which options were invalidated, and by what evidence or constraint?
- Which assumptions survived exploration?
- What uncertainty remains, and why is it acceptable for this plan?
- Which option are we choosing, and why did it survive comparison?
- What trade-offs or risks are we accepting?
- What is explicitly out of scope?

### Agree on Scope

Before you present the plan, align on the boundaries that prevent drift. Decide what the work includes, what it excludes, what success looks like, which assumptions are stable enough to proceed on, and which unresolved questions matter enough to resolve now. Make uncertainty explicit rather than hiding it: if it could change the recommended approach, keep exploring; if it can be managed within the plan, name the risk or boundary. Do not hide unresolved decisions inside tasks; if a task depends on a decision that has not been made, make the decision before formalising.

### Present the Plan for Approval

Present the plan only after discovery and discussion have converged. Convergence requires a final recommendation, not just a list of options: you should be able to state which alternatives were invalidated, which assumptions survived, what uncertainty remains, and why the recommended plan is the best next step. The plan should reflect the agreed direction, not introduce new thinking.

Write the plan so it stands on its own. It is the durable record of the work — specific enough that another agent, or you after the discussion has scrolled out of context, could execute it without reconstructing the conversation. Inline the evidence, decisions, file paths, commands, and constraints needed to act; never lean on "as discussed above" or assumed shared memory.

Structure it around these sections:

- **Goal** — one sentence: what are we achieving
- **Context** — what exists, constraints, what triggered this work
- **Design** — the agreed approach: patterns, trade-offs, decisions, and why this over the alternatives
- **Success** — plan-level success criteria, concrete and verifiable
- **Boundaries** — what's out of scope, to prevent drift
- **Tasks** — ordered steps, each with what it involves and what done looks like

Present the plan in plan mode and hand it to the user for approval (ExitPlanMode). The user approves it or asks for changes; if they request changes, address the feedback and re-present. Once approved, begin the work — turn the tasks into your todo list and execute them in order.

---

## What Good Looks Like

A good plan is fully self-contained: specific enough that another agent could execute it from the plan alone.

- **Goal** — one clear outcome, not a vague improvement area
- **Context** — evidence from the actual system, source data, workflow, or user need
- **Design** — the chosen approach, why it survived comparison, which alternatives were invalidated, which assumptions remain, and what uncertainty is accepted
- **Success** — concrete, verifiable criteria
- **Boundaries** — explicit exclusions that prevent drift
- **Tasks** — ordered execution chunks that follow from the agreed approach

The design section is where the thinking lives. Do not just describe what will be built or run; explain the trade-offs and decisions that make this plan coherent.

---

## Anti-Patterns

A plan is **not**:

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

Ordered list. Smallest meaningful units of work — logical chunks, not individual file edits. Each task needs a label, a description (what and why), and criteria (what done looks like for this task). Tasks should follow directly from the agreed approach; if a task requires a decision that has not been made, make that decision before formalising.
