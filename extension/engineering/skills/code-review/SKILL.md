---
name: code-review
description: Multi-dimensional code review of a pull request
---

# Code Review

Structured evaluation methodology for code review. Assess changes across multiple dimensions with calibrated severity and actionable feedback.

## Purpose

Transform ad-hoc code review into systematic evaluation. Ensure consistent coverage of quality dimensions while calibrating depth to change size.

## Review Flow

### Step 1: Checkout the Branch

```bash
gh pr checkout <PR_NUMBER>
```

If no PR number provided, review the current branch's changes compared to the base branch.

### Step 2: Gather Context

Load `/skill:context-gatherer` to collect PR metadata, linked issues, and author intent. Present a brief summary before beginning review.

### Step 3: Review

Review the changes across all dimensions defined in `references/DIMENSIONS.md`. Apply the confidence scoring from `references/SCORING.md` to filter findings.

For specialized analysis, load these skills as needed:
- `/skill:security-review` — vulnerabilities, auth, data exposure
- `/skill:test-review` — coverage, test quality
- `/skill:code-documentation` — comment accuracy, documentation quality (see its Review & Analysis section)
- `/skill:code-simplification` — simplification opportunities

Collect all findings, grouped by severity.

### Step 4: Verdict

Synthesize findings into a decision: **Approve** / **Request Changes** / **Comment**

Apply the verdict guidelines below to weigh findings and reach a conclusion.

### Step 5: Follow-up

Support drill-down requests until the user is done. Be prepared to:
- Elaborate on specific findings
- Suggest fixes for identified issues
- Re-review after changes are made

## Verdict Guidelines

### Decision Matrix

| Findings | Verdict |
|----------|---------|
| Any 🔴 blockers | **Request Changes** |
| Multiple 🟠 majors (3+) | **Request Changes** |
| Few 🟠 majors (1-2), discussable | **Comment** with concerns |
| Only 🟡 minors and 🟢 nitpicks | **Approve** |
| Clean review | **Approve** with positive notes |

### Weighting Factors

Not all findings are equal. Weight by impact:

**Heavier weight:**
- Security vulnerabilities (even minor ones compound)
- Data integrity risks
- Breaking changes without migration path
- Missing tests for critical paths

**Lighter weight:**
- Style preferences in non-team codebases
- Documentation gaps in internal tools
- Performance in non-hot paths
- Naming nitpicks

### Context Matters

Adjust verdict based on:
- **Author experience** — new contributor vs. senior engineer
- **Change urgency** — hotfix vs. feature work
- **Codebase state** — greenfield vs. legacy constraints
- **Team norms** — strict vs. pragmatic review culture

### Edge Cases

**Comment vs. Request Changes:**
- Use **Comment** when issues are discussable and you'd accept author's pushback
- Use **Request Changes** when issues must be addressed before merge

**Approve with reservations:**
- Approve but note concerns for future work
- "Approving, but consider X before this pattern spreads"

## Review Dimensions

Evaluate code changes across these 8 dimensions:

| Dimension | Focus |
|-----------|-------|
| **Correctness** | Does the code do what it claims? |
| **Scope Fit** | Does the PR stay focused on one concern? |
| **Design** | Does it follow architectural patterns? |
| **Testing** | Are changes adequately tested? |
| **Readability** | Is the code clear and maintainable? |
| **Security** | Are there vulnerabilities or risks? |
| **Performance** | Are there efficiency concerns? |
| **Documentation** | Are changes documented appropriately? |

For detailed checklists per dimension, see `references/DIMENSIONS.md`.

## Severity Levels

Classify findings by impact and required action:

| Level | Indicator | Meaning | Action |
|-------|-----------|---------|--------|
| Blocker | 🔴 | Must fix before merge | Request changes |
| Major | 🟠 | Should fix, but discussable | Request changes or comment |
| Minor | 🟡 | Suggestion, optional improvement | Comment |
| Nitpick | 🟢 | Style preference, take or leave | Comment with "nit:" prefix |

### Severity Guidelines

**Blocker (🔴)**
- Security vulnerabilities
- Data corruption risks
- Broken functionality
- Critical logic errors
- Missing required tests

**Major (🟠)**
- Significant design issues
- Performance problems in hot paths
- Incomplete error handling
- Missing important test cases
- Unclear ownership of responsibilities

**Minor (🟡)**
- Small improvements to clarity
- Additional edge case tests
- Documentation enhancements
- Minor refactoring opportunities

**Nitpick (🟢)**
- Naming preferences
- Code style variations
- Comment wording
- Organization suggestions

## Finding Format

Structure each finding consistently:

```
[DIMENSION] severity — file:line — description

Explanation of the issue with context.

Suggestion (if applicable):
- Specific recommendation
- Code example if helpful
```

**Example:**
```
[SECURITY] 🔴 — src/api/auth.py:42 — SQL injection via unsanitized input

User-provided `username` passed directly to query without sanitization.

Suggestion:
- Use parameterized query: `cursor.execute("SELECT * FROM users WHERE name = ?", (username,))`
```

## Calibration by Change Size

Adjust review depth based on changeset scope:

| Size | Files | Approach |
|------|-------|----------|
| Small | <10 | Full review, all 8 dimensions |
| Medium | 10-30 | Standard review, focus on core changes |
| Large | 30-50 | Warn user; prioritize security, tests, core logic |
| Very Large | 50+ | Strong warning; review by logical grouping |

**Large Changeset Handling:**
1. Acknowledge the size: "This is a large changeset (X files). I'll focus on critical areas first."
2. Prioritize: Security → Correctness → Testing → Design → Others
3. Offer staged review: "Want me to focus on the API layer first, then move to storage?"
4. Note skipped areas: "Deferred: documentation changes, minor refactors"

## Output Template

```markdown
## PR Review Summary

**Overall**: [Approve / Request Changes / Comment]

**Scope**: X files, ~Y lines changed

### Blocking Issues (🔴)
- [DIMENSION] file:line — description

### Major Issues (🟠)
- [DIMENSION] file:line — description

### Minor Suggestions (🟡)
- [DIMENSION] file:line — description

### Nitpicks (🟢)
- nit: file:line — description

### Positive Notes
- Well-tested error handling in `error_handler.py`
- Clear separation of concerns in new modules

### Questions for Author
- Why was X approach chosen over Y?
- Is the performance impact of Z acceptable?
```