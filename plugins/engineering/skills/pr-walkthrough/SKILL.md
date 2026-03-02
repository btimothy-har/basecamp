---
name: pr-walkthrough
description: Interactive step-by-step walkthrough of a pull request
allowed-tools: Bash(git:*), Bash(gh:*)
---

# PR Walkthrough

Interactive, step-by-step teaching of pull request changes. Transform code review from passive reading into active understanding.

## Purpose

Guide reviewers through PR changes progressively, ensuring comprehension at each step before moving forward. Focus on the "why" behind changes while grounding explanations in specific code locations.

## Walkthrough Flow

### Step 1: Checkout the Branch

```bash
gh pr checkout <PR_NUMBER>
```

If no PR number provided, work with the current branch's changes compared to the base branch.

### Step 2: Gather Context

Use the **context-gatherer** agent to collect PR metadata, linked issues, and author intent. Present a brief summary before beginning the walkthrough.

### Step 3: Set the Stage

Provide the one-liner and problem statement.

**Deliver:**
- Single sentence summarizing what the PR accomplishes
- Problem or need that motivated the change
- Scope indicator (how many files, rough complexity)

**Example:**
> This PR adds rate limiting to the API to prevent abuse during traffic spikes.
>
> **Problem**: Unlimited API requests were causing database connection exhaustion during peak hours.
>
> **Scope**: 4 files changed, adds new middleware + configuration.

### Step 4: Entry Point

Show where the change begins execution.

**Identify:**
- The first file/function where the new behavior triggers
- How this integrates with existing code paths
- What conditions activate this code

**Cite code:**
```
The rate limiter hooks into the request lifecycle via middleware registration:

`app/main.py:23-25`
```python
app.add_middleware(RateLimitMiddleware)
```

This runs before every request reaches route handlers.
```

### Step 5: Data Flow

Trace through the system with citations at each step.

**Walk through:**
1. Input handling — what data enters and how
2. Processing — transformations, validations, business logic
3. Side effects — database calls, external services, state changes
4. Output — what returns to the caller

**Pattern:**
```
Step 1: Request enters middleware (`middleware/rate_limit.py:15`)
Step 2: Client IP extracted (`middleware/rate_limit.py:18-20`)
Step 3: Token bucket checked (`middleware/rate_limit.py:25-30`)
Step 4: Request proceeds or 429 returned (`middleware/rate_limit.py:35-42`)
```

### Step 6: Key Decisions

Highlight architectural choices and trade-offs.

**Surface:**
- Why this approach over alternatives
- Trade-offs made (performance vs simplicity, etc.)
- Assumptions embedded in the design
- Future implications or constraints introduced

**Example:**
> The author chose a token bucket algorithm over sliding window:
> - Token bucket (`rate_limit.py:25`) allows burst handling
> - Trade-off: Slightly more complex state management
> - Alternative considered: Sliding window would provide smoother limits but require per-request timestamp storage

### Step 7: Tests

Explain what's tested and how.

**Cover:**
- Test file locations with citations
- What scenarios are covered
- Notable test techniques (mocking, fixtures, edge cases)
- Any gaps in coverage

**Example:**
```
Tests in `tests/test_rate_limit.py`:
- `test_under_limit` (line 15): Verifies requests pass when under limit
- `test_at_limit` (line 28): Boundary condition at exact limit
- `test_over_limit` (line 42): Confirms 429 response
- `test_burst_recovery` (line 58): Tests token regeneration

Gap: No integration test with actual concurrent requests.
```

### Step 8: Wrap Up

Summarize and prompt for questions.

**Provide:**
- Brief recap of what was added/changed
- Key takeaways for the reviewer
- Open questions for the PR author
- Suggested focus areas for deeper review

**Example:**
> **Summary**: Rate limiting middleware using token bucket algorithm, configured per-endpoint via `config.py`.
>
> **Key takeaways**:
> - Limits enforced at middleware layer, before any business logic
> - Configuration allows per-route tuning
> - Headers communicate limit status to clients
>
> **Questions for author**:
> - Why 100 requests/minute default? Based on load testing?
> - Should admin endpoints have different limits?
>
> **Suggested focus**: Security review of IP extraction logic (spoofing via X-Forwarded-For?)

## Core Principles

**Progressive Teaching**
- Present one concept at a time, not document dumps
- Confirm understanding before advancing
- Build from entry point to full system impact

**Code-Grounded Explanations**
- Every reference includes file and line: `src/api/auth.py:42`
- Quote relevant code snippets inline
- Link explanations to specific implementation details

**Follow the Data**
- Start where execution begins
- Trace data flow through the system
- Show cause-and-effect chains

**Surface the Non-Obvious**
- Highlight architectural decisions
- Explain trade-offs made
- Note where author chose one approach over alternatives

## Pacing Adjustments

Adapt pace based on reviewer signals:

| Signal | Response |
|--------|----------|
| "Makes sense" / "Got it" | Move to next stage |
| "Wait, what?" / Confusion | Slow down, add context, re-explain |
| "Skip ahead" / "I get it" | Summarize remaining stages, jump to wrap-up |
| Question asked | Answer fully before continuing |
| Deep dive request | Expand that area, pause progression |
| "Let's come back to this" | Note it, continue, revisit in wrap-up |

## Citation Format

Always use consistent citation format:

**File reference**: `path/to/file.py:line`
**Line range**: `path/to/file.py:10-25`
**Function reference**: `path/to/file.py:function_name` (with line if helpful)

**In prose:**
> The validation happens in `validators.py:validate_input` (line 42), which calls...

**In lists:**
```
- Input parsing (`api/handlers.py:15-20`)
- Validation (`validators.py:42`)
- Database write (`db/models.py:create_user`)
```

## Handling Large PRs

For PRs with many changes:

1. **Group by logical unit** — Review related files together
2. **Prioritize critical paths** — Start with entry points and core logic
3. **Defer peripheral changes** — Note documentation/config updates for later
4. **Offer checkpoints** — "Want to pause here before moving to the next module?"
