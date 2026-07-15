---
name: gather
description: "Requirements-gathering guidance for task starts, ambiguity, scope clarification, and user questions. Task start triggers: 'help me with', 'I want to', 'build/create/implement', and feature requests. Mid-task triggers: clarifying requirements, small non-architectural decisions, handling edge cases, and confirming decisions. Architectural, multi-step, or consequential approach discovery belongs in planning."
---

# Gather

## Purpose

Gather information from users to enable informed execution. This skill provides interview techniques (micro-skills) and a lightweight pipeline for turning ambiguous requests into clear requirements.

Apply gather as the front door for requirements ambiguity, scope clarification, preferences, priorities, and small discovery gaps. When the request requires architectural exploration, multi-step implementation strategy, or consequential approach selection, gather enough context to name the uncertainty, then apply the `planning` skill.

---

## Interview Techniques

Micro-skills for extracting information. Apply in order of preference—start with clarifying questions; escalate when simpler approaches don't surface needed information.

### Clarifying Questions

Direct questions to fill specific information gaps.

**When**: First technique for any ambiguity. Most gaps resolve here.

**Approach**:
- Identify the specific gap
- Ask a focused question targeting that gap
- Offer concrete options when possible

**Examples**:
- "Found two valid approaches for the cache layer: Redis (faster, requires setup) or in-memory (simpler, less durable). Which fits better?"
- "The API can return either JSON or XML. Which format is needed?"
- "Should this validation run on blur or on submit?"

### Scenario Probing

Explore "what if" situations to uncover edge case handling.

**When**: Happy path is clear but specific edge case handling isn't.

**Approach**:
- Present the specific scenario encountered
- Ask what should happen
- Offer reasonable options if applicable

**Examples**:
- "What should happen if a user tries to delete their last payment method?"
- "If this API call fails, should it retry, show an error, or use cached data?"
- "The file might not exist. Fail silently or show a warning?"

### Preference Comparison

Present concrete options when implementation could reasonably go either way.

**When**: Multiple valid approaches exist for a specific implementation detail.

**Approach**:
- Present 2-3 distinct, viable options
- Describe trade-offs briefly
- Let the choice reveal priority

**Examples**:
- "Timestamps can store as UTC (simpler queries) or local time (easier display). Preference?"
- "Error messages can be technical (debugging) or user-friendly (UX). Which audience?"

### Priority Ranking

Ask the user to rank competing concerns when trade-offs are unavoidable.

**When**: A specific decision involves conflicting goals.

**Approach**:
- Identify the 2-3 competing concerns
- Ask which matters most for this decision
- Use ranking to resolve the specific trade-off

**Examples**:
- "For this endpoint: response speed vs. data freshness—which matters more?"
- "This refactor can prioritize: backward compatibility, code clarity, or performance. Top priority?"

### Presenting Options

When applying interview techniques, present structured options whenever possible. Options are faster for users to answer than open-ended questions, and ensure decisions are captured clearly.

| Technique | Pattern |
|-----------|---------|
| Clarifying questions | 2-3 labeled options with brief descriptions |
| Scenario probing | 2-3 handling approaches to choose from |
| Preference comparison | 2-3 options with trade-off descriptions |
| Priority ranking | List items, ask to rank in priority order |

**When to present options**:
- Choosing between approaches
- Confirming a decision
- Gathering preferences
- Any question with identifiable alternatives

**When plain text is fine**:
- Truly open-ended questions with no reasonable options to offer
- Follow-up clarification on a previous answer

**Best practices**:
- Keep option labels to 1-5 words
- Use descriptions to explain trade-offs
- Limit to 2-4 options
- Provide context in the question itself, not just in options

---

## Pipeline

Three phases that turn ambiguous requests into clear requirements. Keep the process lightweight and proportional to the uncertainty.

```
Task/Gap arrives
  |
Phase 1: Interview (gather context)
  |
Phase 2: Clarify (resolve lightweight uncertainty)
  |
Phase 3: Capture (document requirements)
  |
Execute or hand off to planning
```

Use the lightest process that resolves the uncertainty:
- **Small/simple gaps**: ask one concise clarifying question, offer concrete options when useful, then proceed.
- **Requirements and scope ambiguity**: interview until success criteria, boundaries, constraints, edge cases, and priorities are clear enough to execute.
- **Architectural, multi-step, or consequential approach discovery**: identify the key assumptions/questions, then use `planning` for full falsification, convergence, and execution handoff.

Continue until requirements are clear enough to proceed or the remaining uncertainty belongs in `planning`.

### Phase 1: Interview

Gather context from the user that cannot be discovered autonomously.

**Before engaging the user**: Complete autonomous investigation first—explore codebase, review patterns, check documentation. This enables informed questions rather than generic ones.

**During interview**: Apply interview techniques (clarifying questions, scenario probing, preference comparison, priority ranking) to surface requirements.

**Scaling**: Small gap → one focused question. New feature → multiple rounds until requirements are clear.

### Phase 2: Clarify

Resolve lightweight uncertainty constructively and collaboratively. Gather should clarify requirements, not own full architecture-level falsification or convergence.

**Approach**:
1. **Choose depth** — Small/simple gap → quick confirmation. Broader requirements ambiguity → focused interview. Consequential approach uncertainty → hand off to `planning`.
2. **Name the uncertainty** — State the specific missing requirement, scenario, preference, priority, or boundary.
3. **Offer concrete options** — Present 2-3 viable choices when helpful, with brief trade-offs.
4. **Probe scenarios** — Ask about edge cases or failure modes that affect requirements.
5. **Negotiate scope** — Apply YAGNI, suggest phasing, and separate must-haves from future ideas.
6. **Confirm the result** — Summarize what is in scope, out of scope, and how the clarified case should behave.

**Small/Simple Gap Pattern**:
```
I found one unclear detail: [specific gap].
Do you want A ([trade-off]) or B ([trade-off])?
```

**Requirements Clarification Pattern**:
```
To make this executable, I need to clarify [specific requirement/scope gap].
The main options are:
A. **[Option A]** — [brief trade-off]
B. **[Option B]** — [brief trade-off]

Which matches your intent?
```

**Planning Handoff Pattern**:
```
This looks consequential enough that the remaining uncertainty is about approach, not just requirements.
I think the key assumptions/questions are:
- [Assumption/question 1]
- [Assumption/question 2]
- [Assumption/question 3]

I'll switch to `planning` to evaluate the options and converge on an implementation path.
```

**Scope Negotiation**:

| Situation | Response |
|-----------|----------|
| Feature creep | "Good idea—add to a future phase?" |
| Gold-plating | "What failure would require that extra complexity?" |
| Unclear priority | "If only two of these three, which two matter most?" |
| Constraint pressure | "Given constraints, which requirement is safest to defer?" |

**Scaling**: Small gap → concise clarifying question and quick confirmation. Requirements ambiguity → focused interview and capture. Architectural, multi-step, or consequential implementation choices → identify assumptions/questions and apply `planning`.

### Phase 3: Capture

Document agreed requirements for execution.

**What to Capture**:

| Category | Questions Answered |
|----------|-------------------|
| Success criteria | What does "done" look like? How to verify? |
| Scope boundaries | What's included? What's excluded? |
| Constraints | Technical limitations? User preferences? Non-negotiables? |
| Edge cases | Unexpected inputs? Error conditions? |
| Priorities | When trade-offs arise, what matters most? |

**Completeness Check** — Requirements are complete when answering "yes" to all:
1. Could tests be written now? — Success criteria are concrete
2. Would another developer understand the scope? — Boundaries are explicit
3. Are edge cases covered? — Failure modes have handling
4. Can execution proceed without clarification? — No questions would arise

**Confirmation**: Summarize back to user: "To confirm: building X with Y behavior. Edge case Z handled by... Does this capture it?"

**Scaling**: Small gap → mental note, resume. New feature → document in workspace.

---

## Core Principles

- **One question at a time** — Don't batch multiple unrelated questions
- **Specific, not general** — Ask about concrete situations, not abstract preferences
- **Context first** — Briefly explain what led to the question
- **Options when possible** — Easier to pick than open-ended
- **Respect signals** — If user says "just pick one," use your judgment
- **Stay non-mutative** — Do not create files, edit code, or delegate implementation work while resolving requirements

---

## Anti-Patterns

| Anti-Pattern | Problem | Instead |
|--------------|---------|---------|
| Question dump | Overwhelms; gets shallow answers | One question at a time |
| Jumping to implementation | Builds wrong thing | Complete discovery first |
| No pushback on scope | Scope bloats, delivery slips | Apply YAGNI; suggest phasing |
| Vague questions | Yields vague answers | Ask about specific scenarios |
| Over-interviewing | Constant interruptions frustrate | Scale to context depth |
| Skipping discovery | Assumes context is known | Run pipeline, scaled appropriately |
| Ignoring "use your judgment" | User wants to move on | Respect delegation signals |
