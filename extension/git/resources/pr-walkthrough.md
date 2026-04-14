# PR Walkthrough — PR #{{PR_NUMBER}}

Interactive, step-by-step walkthrough of PR #{{PR_NUMBER}} on branch `{{BRANCH}}`.

## Step 1: Gather Context

```bash
git log --oneline origin/{{BASE}}..HEAD
git diff --stat origin/{{BASE}}...HEAD
```

Check for linked issues and PR description:
```bash
gh pr view {{PR_NUMBER}} --json title,body,labels,assignees
```

Present a brief summary before beginning the walkthrough.

## Step 2: Set the Stage

Provide:
- Single sentence summarizing what the PR accomplishes
- Problem or need that motivated the change
- Scope indicator (how many files, rough complexity)

## Step 3: Entry Point

Identify where the change begins execution:
- The first file/function where the new behavior triggers
- How this integrates with existing code paths
- What conditions activate this code

Quote relevant code with file and line references.

## Step 4: Data Flow

Trace through the system, citing code at each step:
1. Input handling — what data enters and how
2. Processing — transformations, validations, business logic
3. Side effects — database calls, external services, state changes
4. Output — what returns to the caller

## Step 5: Key Decisions

Highlight architectural choices and trade-offs:
- Why this approach over alternatives
- Trade-offs made (performance vs simplicity, etc.)
- Assumptions embedded in the design
- Future implications or constraints introduced

## Step 6: Tests

Cover:
- Test file locations with line references
- What scenarios are covered
- Notable test techniques (mocking, fixtures, edge cases)
- Any gaps in coverage

## Step 7: Wrap Up

Provide:
- Brief recap of what was added/changed
- Key takeaways for the reviewer
- Open questions for the PR author
- Suggested focus areas for deeper review

## Pacing

Adapt based on user signals:

| Signal | Response |
|--------|----------|
| "Makes sense" / "Got it" | Move to next step |
| Confusion | Slow down, add context, re-explain |
| "Skip ahead" | Summarize remaining, jump to wrap-up |
| Question asked | Answer fully before continuing |
| Deep dive request | Expand that area, pause progression |

## Citation Format

- File reference: `path/to/file.py:42`
- Line range: `path/to/file.py:10-25`
- In prose: "The validation happens in `validators.py:validate_input` (line 42), which calls..."
