---
name: context-gatherer
description: Gather comprehensive context before starting work. Supports PR review (metadata, diff, linked issues), task implementation (codebase patterns), issue investigation (details, related PRs), and refactoring (callers, dependents, impact radius).
disable-model-invocation: true
---

# Context Gatherer

Collect and organize all relevant information for a task before any implementation begins. Detect the context type from the request, gather systematically, and present structured findings.

## Context Types

### PR Context
**Triggers**: "PR #123", "pull request", "review this PR", branch comparison

**Sources**:
- `gh pr view` for PR metadata, description, labels
- `gh pr diff` for code changes
- Linked issues via PR description
- Commit history for the PR
- Author's stated intent

**Output focus**: What changed, why, scope, linked requirements

### Task Context
**Triggers**: "implement X", "add feature", "build", "create"

**Sources**:
- Codebase exploration (similar patterns, related files)
- Project CLAUDE.md for conventions
- Existing tests for expected behavior
- Dependencies and interfaces

**Output focus**: Where to implement, existing patterns, constraints

### Issue Context
**Triggers**: "issue #456", "bug report", "investigate", "reported problem"

**Sources**:
- `gh issue view` for issue details
- Related PRs (linked or mentioned)
- Recent commits to affected areas
- Error logs or reproduction steps if provided

**Output focus**: Problem statement, reproduction, affected code, history

### Refactor Context
**Triggers**: "refactor", "rename", "move", "extract", "restructure"

**Sources**:
- All callers/usages of target code
- Dependent modules and interfaces
- Test coverage of target
- Related patterns elsewhere in codebase

**Output focus**: Impact radius, dependencies, safe transformation boundaries

## Workflow

### Step 1: Detect Type

Identify which context type applies from the user's request. If ambiguous, ask.

### Step 2: Collect

Systematically gather from the appropriate sources listed above. Use `gh`, `git`, `grep`, `find`, and file reads as needed.

### Step 3: Organize

Structure findings by relevance and category using the output template below.

### Step 4: Identify Gaps

Note what information is missing or unclear. Surface clarifying questions.

## Output Template

```markdown
## Context Summary

**Type**: [PR | Task | Issue | Refactor]
**Subject**: [Brief identifier]

---

### Understanding

[Restated objective in clear terms]
[Core problem or opportunity]
[Success indicators]

---

### Gathered Context

#### Primary Sources
- [Source 1]: [Key findings]
- [Source 2]: [Key findings]

#### Relevant Files
| File | Relevance |
|------|-----------|
| `path/to/file.py` | [Why it matters] |

#### Patterns & Conventions
- [Existing pattern to follow]
- [Convention from CLAUDE.md]

#### Dependencies & Connections
- [Component A] → [Component B]: [Relationship]

---

### Gaps & Questions

**Missing Information**:
- [What couldn't be determined]

**Questions for User**:
1. [Clarifying question]
2. [Decision needed]

---

### Recommended Next Steps

1. [Logical first action]
2. [Follow-up action]
```

## Guidelines

- **Thorough but focused** — explore widely, report only relevant findings
- **Findings vs. inferences** — clearly label what was found vs. what was concluded; note confidence levels for uncertain items
- **Enable action** — context should make next steps obvious; surface blockers early

## Scope

Gather and organize context only. Do not propose implementations, make architectural decisions, write code, or create acceptance criteria.
