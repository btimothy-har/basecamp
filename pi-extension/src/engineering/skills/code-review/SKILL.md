---
name: code-review
description: Multi-dimensional code review using specialized sub-agents
---

# Code Review

Dispatch specialized review agents to analyze code changes in parallel, then synthesize their findings into an interactive `review_packet`.

## Step 1: Determine Scope

Identify what to review. Use the user's input — a PR number, branch, file list, or default to unstaged changes.

Gather:
- Scope summary: what changed, rough line count, affected subsystems, and intent from PR metadata, commits, or the user
- Diff anchors: `base`, optional `head`, and relevant paths for changed-code evidence
- Review focus or constraints from the user

Structured diff references use this shape:

```json
{ "diff": { "base": "origin/main", "head": "feature", "path": "src/file.ts", "lineStart": 42, "lineEnd": 58, "contextLines": 5 } }
```

Use `base` alone for `git diff base -- path`; use `base` + `head` for merge-base range `git diff base...head -- path`. `path` may be omitted when it matches the reference path. Keep `contextLines` small and never above 50.

## Step 2: Dispatch Reviewers

Use the `agent` tool to dispatch all 4 agents in the same assistant turn. Include the scope summary, base/head anchors, relevant file paths, and this evidence contract in each task:

> For each finding, include file/line plus a structured `evidence` reference with `path`, optional `lineStart`/`lineEnd`, required `whyRelevant`, and `diff` for changed-code evidence. Do not paste code diffs inline. Use `quote` only for static/non-diff excerpts that cannot be represented by `diff`.

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
- Does the evidence cite file/line and include a structured diff reference for changed-code evidence?

## Step 4: Build Review Packet and Verdict

Build `review_packet` cards from verified findings, grouped by severity and dimension. Each finding card should include:
- Title with severity, dimension, and affected file/function
- Body with concise impact and remediation guidance
- `references[]` from the specialist evidence, preserving structured `diff` refs for changed-code evidence

Call `review_packet` for interactive display. Do not output a long standalone markdown verdict instead of the packet.

Verdict guidance:

| Findings | Verdict |
|----------|---------|
| Any 🔴 blockers | **Request Changes** |
| Multiple 🟠 majors (3+) | **Request Changes** |
| Few 🟠 majors (1-2), discussable | **Comment** with concerns |
| Only 🟡 minors and 🟢 nitpicks | **Approve** |
| Clean review | **Approve** with positive notes |

Weight by impact — security vulnerabilities, data integrity risks, and missing tests for critical paths weigh heavier. Style preferences, documentation gaps in internal tools, and naming nitpicks weigh lighter.

## Fallback Output

If `review_packet` is unavailable, provide concise markdown without inline code diffs:

```markdown
## Code Review

**Verdict**: Approve / Request Changes / Comment
**Scope**: X files, ~Y lines changed

### 🔴 Blocking Issues (90–100)
- [DIMENSION] file:line — description
  Evidence: structured diff ref `{ base, head?, path?, lineStart?, lineEnd?, contextLines? }`

### 🟠 Important Issues (80–89)
- [DIMENSION] file:line — description
  Evidence: structured diff ref `{ base, head?, path?, lineStart?, lineEnd?, contextLines? }`

### Positive Notes
- What's well done

### Questions
- Anything that needs clarification from the author
```
