---
name: test-review
description: Analyze test quality and coverage for code changes. Evaluate coverage gaps, edge cases, mock quality, readability, and assertion design. Use when reviewing PRs that include tests or assessing whether new code is adequately tested.
disable-model-invocation: true
---

# Test Reviewer

Evaluate whether code changes are adequately tested and whether existing tests are well-designed. Report findings — do not write tests directly.

For Python projects, load `/skill:python-development` and read its [TESTING.md](../python-development/references/TESTING.md) reference for pytest-specific patterns.

## Workflow

### Step 1: Identify Changes

Determine the source files that changed. Use the scope provided by the user, or default to unstaged changes:

```bash
git diff --name-only
```

### Step 2: Locate Tests

Find test files corresponding to the changed source files. Check:
- `tests/` directory mirroring source structure
- Co-located test files (`*_test.py`, `test_*.py`)
- Test files referenced in changed code

### Step 3: Map Coverage

For each changed source file, identify:
- Which functions/methods have corresponding tests
- Which functions/methods lack test coverage
- Whether modified behaviors have updated tests

### Step 4: Evaluate Quality

Assess each test against these dimensions:

**Coverage**
- Are new code paths tested?
- Are modified behaviors verified?
- Are critical paths prioritized?

**Edge Cases**
- Boundary values (0, 1, max, empty)
- Error conditions and exceptions
- Null/None/undefined inputs
- Concurrent access scenarios
- Timeout and retry behaviors

**Mock & Fixture Quality**
- Are mocks at appropriate boundaries?
- Do mocks verify interactions?
- Are fixtures reusable and focused?
- Is test isolation maintained?

**Readability**
- Clear test names describing behavior
- Arrange-Act-Assert structure
- Minimal setup noise
- Intent visible without scrolling

**Assertion Quality**
- Assertions test actual requirements
- Error messages are descriptive
- No over-testing implementation details
- Appropriate assertion granularity

### Step 5: Report

```markdown
## Test Review Summary

**Coverage**: [Good / Partial / Insufficient]
**Test Files Analyzed**: X files, Y tests

### Coverage Gaps
- `file.py:function_name` — No test for error path
- `file.py:method` — Missing edge case: empty input

### Test Quality Issues
- `test_file.py:test_name` — [issue description]

### Well-Designed Tests
- `test_file.py:test_name` — [why it's good]

### Recommendations
1. [Priority addition/improvement]
2. [Additional suggestion]
```

For each finding, use this format:

```
[CATEGORY] file:line — description

What's missing or problematic.

Suggestion:
- Specific test to add or improvement to make
```

**Categories**: `[COVERAGE]`, `[EDGE_CASE]`, `[MOCK]`, `[READABILITY]`, `[ASSERTION]`

## Quality Standards

**Good test coverage includes:**
- Happy path for new functionality
- At least one error/failure case
- Boundary conditions for numeric inputs
- Empty/null handling where applicable
- Integration with adjacent components

**Good test design includes:**
- One behavior per test
- Descriptive names (`test_when_X_then_Y`)
- Minimal mocking (test behavior, not implementation)
- Fast execution (no unnecessary I/O)
- Deterministic results (no flaky tests)

## Scope

**In scope**: Test coverage, test design, test readability, mock/fixture quality, assertion quality.

**Out of scope**: Implementation correctness, security vulnerabilities, documentation quality, architectural decisions.
