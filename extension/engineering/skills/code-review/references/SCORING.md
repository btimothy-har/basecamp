# Confidence Scoring

Rate each finding from 0–100 before including it in the review output.

| Range | Meaning |
|-------|---------|
| 0–25 | Likely false positive or pre-existing issue |
| 26–50 | Minor nitpick not explicitly covered in guidelines |
| 51–75 | Valid but low-impact issue |
| 76–90 | Important issue requiring attention |
| 91–100 | Critical bug or explicit guideline violation |

**Only report findings with confidence ≥ 80.**

## Scoring Checklist

Before assigning a score, verify:

1. **Is this a real issue?** — Confirm the code path is reachable and the behavior is incorrect or risky.
2. **Is it new?** — Pre-existing issues in unchanged code score lower; only flag if the change worsens them.
3. **Is it covered by guidelines?** — Issues explicitly addressed in CLAUDE.md or loaded skills score higher.
4. **What's the impact?** — Bugs in hot paths or security-sensitive code score higher than cosmetic issues.
5. **Is there context you're missing?** — Check for compensating controls, test coverage, or documented exceptions before reporting.

## Output Format

Structure findings by confidence tier:

```
### 🔴 Critical Issues (90–100)
- [DIMENSION] file:line — description
  Explanation and fix suggestion

### 🟠 Important Issues (80–89)
- [DIMENSION] file:line — description
  Explanation and fix suggestion

### ✅ Positive Highlights
- Well-implemented patterns worth noting
```

Findings below 80 are omitted. Quality over quantity — every reported issue should be actionable.
