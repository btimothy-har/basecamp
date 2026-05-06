---
name: gather
description: "Invoke when gathering requirements or asking questions. Task start triggers: 'help me with', 'I want to', 'build/create/implement', feature requests, architectural decisions, scope clarification. Mid-task triggers: clarifying requirements, choosing approaches, handling edge cases, confirming decisions. Adapts depth to context."
---

# Gather

## Purpose

Gather information from users to enable informed execution. This skill provides interview techniques (micro-skills) and a pipeline (process) for turning ambiguous requests into clear requirements.

The pipeline runs for both task-start and mid-task triggers. Each phase scales to context—a small gap needs brief treatment; a new feature needs full exploration.

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

Three phases that turn ambiguous requests into clear requirements. Each phase scales to context depth—run briefly for small gaps, thoroughly for complex features/refactors/architectural decisions.

```
Task/Gap arrives
  |
Phase 1: Interview (gather context)
  |
Phase 2: Discover (test assumptions before converging)
  |
Phase 3: Capture (document requirements)
  |
Execute with full understanding
```

Use the lightest process that resolves the uncertainty:
- **Small/simple gaps**: ask one concise clarifying question, offer concrete options when useful, then proceed.
- **Complex features/refactors/architectural decisions**: collaborate falsification-first—map assumptions, test strawmen and scenarios, look for disconfirming evidence, then converge.

Continue each phase until the user indicates readiness to proceed.

### Phase 1: Interview

Gather context from the user that cannot be discovered autonomously.

**Before engaging the user**: Complete autonomous investigation first—explore codebase, review patterns, check documentation. This enables informed questions rather than generic ones.

**During interview**: Apply interview techniques (clarifying questions, scenario probing, preference comparison, priority ranking) to surface requirements.

**Scaling**: Small gap → one focused question. New feature → multiple rounds until requirements are clear.

### Phase 2: Discover

Turn gathered context into agreed approaches through collaborative falsification before recommendation. Keep the posture constructive, curious, and practical.

**Approach**:
1. **Choose depth** — Small/simple gap → quick confirmation. Complex work → falsification-first discovery.
2. **Map assumptions** — Name what must be true for the request or approach to work.
3. **Create disposable strawmen** — Sketch 2-3 lightweight approaches as tools for learning, not proposals to defend.
4. **Falsify scenarios** — Test each strawman against happy paths, edge cases, constraints, and failure modes.
5. **Seek disconfirming evidence** — Ask what would make an option wrong, risky, too complex, or unnecessary.
6. **Apply YAGNI** — Push back on scope; suggest phasing for large ideas.
7. **Converge deliberately** — Only after assumptions and failure modes are clear, summarize the trade-off and recommend or confirm a direction.
8. **Agree on scope** — Confirm: "So we're building X, not Y—correct?"

**Small/Simple Gap Pattern**:
```
I found one unclear detail: [specific gap].
Do you want A ([trade-off]) or B ([trade-off])?
```

**Complex Discovery Pattern**:
```
For [feature/refactor/decision], here are the assumptions I think we need to test:
- [Assumption 1]
- [Assumption 2]
- [Assumption 3]

Disposable strawmen:
A. **[Option A]** (simplest)
   - Works if [assumption]
   - Fails/struggles if [scenario]

B. **[Option B]** (moderate)
   - Works if [assumption]
   - Fails/struggles if [scenario]

C. **[Option C]** (complex)
   - Works if [assumption]
   - Fails/struggles if [scenario]

What evidence, constraint, or scenario would rule these out?
After that, we can converge on the smallest viable path that survives.
```

**Scope Negotiation**:

| Situation | Response |
|-----------|----------|
| Feature creep | "Good idea—add to a future phase?" |
| Gold-plating | "Simpler version might survive the scenarios. What failure would require the extra complexity?" |
| Unclear priority | "If only two of these three, which two matter most?" |
| Time pressure | "Given constraints, what assumption can we safely defer testing?" |
| Early convergence | "Before recommending, let's check what would make this approach wrong." |

**Scaling**: Small gap → concise clarifying question and quick confirmation. Complex work → assumption mapping, disposable strawmen, scenario falsification, disconfirming evidence, then recommendation/convergence.

When discovery produces a consequential implementation path, switch to the `planning` skill to formalize the recommendation, boundaries, and handoff rather than treating the gather pipeline as the execution plan.

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
