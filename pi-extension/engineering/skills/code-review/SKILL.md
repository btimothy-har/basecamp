---
name: code-review
description: Multi-dimensional code review using specialized sub-agents
---

# Code Review

Dispatch specialized review agents to analyze code changes in parallel, then synthesize their findings into a verdict.

## Step 1: Determine Scope

Identify what to review. Use the user's input — a PR number, branch, file list, or default to unstaged changes.

Build a scope summary:
- What changed (files, rough line count)
- The intent behind the changes (PR description, commit messages, linked issues)

## Step 2: Dispatch Reviewers

Use the `agent` tool to dispatch all 4 agents in the same assistant turn. Include the scope summary and relevant file paths in each task.

1. `{ agent: "security-specialist", task: "Review these changes for security vulnerabilities: {scope}" }`
2. `{ agent: "testing-specialist", task: "Review test coverage and quality for these changes: {scope}" }`
3. `{ agent: "docs-specialist", task: "Review documentation accuracy and completeness for these changes: {scope}" }`
4. `{ agent: "code-clarity-specialist", task: "Review these changes for simplification opportunities: {scope}" }`

## Step 3: Synthesize

Collect findings from all 4 reviewers. Apply confidence scoring — only include findings with confidence ≥ 80:

| Range | Meaning |
|-------|---------|
| 91–100 | Critical bug or explicit guideline violation |
| 80–90 | Important issue requiring attention |
| Below 80 | Omit — too speculative or low-impact |

Before scoring, verify each finding:
- Is this a real issue? Is the code path reachable?
- Is it new? Pre-existing issues in unchanged code score lower.
- What's the impact? Hot paths and security-sensitive code score higher.

## Step 4: Verdict

| Findings | Verdict |
|----------|---------|
| Any 🔴 blockers | **Request Changes** |
| Multiple 🟠 majors (3+) | **Request Changes** |
| Few 🟠 majors (1-2), discussable | **Comment** with concerns |
| Only 🟡 minors and 🟢 nitpicks | **Approve** |
| Clean review | **Approve** with positive notes |

Weight by impact — security vulnerabilities, data integrity risks, and missing tests for critical paths weigh heavier. Style preferences, documentation gaps in internal tools, and naming nitpicks weigh lighter.

## Output

```markdown
## Code Review

**Verdict**: Approve / Request Changes / Comment
**Scope**: X files, ~Y lines changed

### 🔴 Blocking Issues (90–100)
- [DIMENSION] file:line — description

### 🟠 Important Issues (80–89)
- [DIMENSION] file:line — description

### Positive Notes
- What's well done

### Questions
- Anything that needs clarification from the author
```
