---
name: code-simplification
description: Analyze code for simplification opportunities — complexity reduction, clarity improvements, redundancy elimination, and pattern alignment. Reports findings without making changes. Use after writing or modifying code, or to audit existing files.
disable-model-invocation: true
---

# Code Simplifier

Identify opportunities to improve code clarity, consistency, and maintainability. Report findings — do not make changes directly.

## Workflow

### Step 1: Determine Scope

Use the scope provided by the user. If none specified, default to unstaged changes:

```bash
git diff --name-only
```

### Step 2: Load Context

- Check for a project CLAUDE.md and read it
- Identify which skills are relevant to the code (e.g., `/skill:python-development`, `/skill:sql`)

### Step 3: Analyze

Read each file in scope. Evaluate against these categories:

**Complexity Reduction**
- Excessive nesting, convoluted control flow
- Overly long functions
- Complex conditionals that could be simplified

**Clarity Improvements**
- Unclear variable/function names
- Missing or misleading abstractions
- Code that requires mental gymnastics to understand

**Redundancy Elimination**
- Duplicated logic across functions or modules
- Unnecessary intermediate variables
- Dead code, redundant type assertions
- Over-engineered abstractions

**Pattern Alignment**
- Deviations from established project patterns
- Inconsistent naming conventions
- Non-idiomatic constructs for the language

**Structure Optimization**
- Functions doing too much (single-responsibility violations)
- Poor separation of concerns
- Logic that would benefit from extraction or consolidation

### Step 4: Score and Filter

Rate each opportunity from 0–100 based on improvement potential:

| Range | Meaning |
|-------|---------|
| 0–25 | Marginal improvement, highly subjective |
| 26–50 | Minor improvement, low priority |
| 51–75 | Moderate improvement, worth considering |
| 76–90 | Significant improvement to clarity or maintainability |
| 91–100 | High-impact simplification, strongly recommended |

**Only report opportunities with impact ≥ 60.**

### Step 5: Report

```markdown
## Simplification Analysis

**Scope**: [files analyzed]
**Guidelines Referenced**: [CLAUDE.md rules, skills loaded]

### High Impact (80–100)
- [CATEGORY] file:line — description
  Current pattern and why it's suboptimal.
  Suggested approach and expected benefit.

### Moderate Impact (60–79)
- [CATEGORY] file:line — description
  Current pattern and why it's suboptimal.
  Suggested approach and expected benefit.

### Summary
[Brief overall assessment. If no significant opportunities exist, confirm the code is well-structured.]
```

## Scope

**In scope**: Complexity reduction, clarity, redundancy, pattern alignment, structure.

**Out of scope**: Security vulnerabilities, test quality, comment accuracy, correctness bugs.

## Constraints

- **Do not make changes** — identify and recommend only
- **Preserve functionality** — all suggestions must maintain exact behavior
- **Avoid over-simplification** — do not recommend changes that sacrifice clarity for brevity
