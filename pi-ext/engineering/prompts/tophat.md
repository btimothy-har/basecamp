---
description: Start a validation-first workflow for the current local change
---
Validate the code changes made on this branch.

Additional focus (if provided): $ARGUMENTS

## Start With Context
1. Use the `gather` skill first to understand the local change before proposing validation.
2. Read the diff, touched files, and nearby code needed to understand intent and blast radius.
3. Use `recall` only if prior session context would materially change what should be validated or how.

## Understand Changed Surfaces and Risk
Identify what actually changed and what could break:
- user-visible flows, CLI commands, prompts, APIs, jobs, or background behavior
- data shape, parsing, persistence, migrations, or queries
- config, env vars, flags, permissions, and deployment/build assumptions
- integrations, side effects, error paths, and rollback sensitivity
- unaffected areas that do *not* need validation, to keep scope tight

## Choose Validation Methods Intentionally
Select the smallest set of high-signal checks that can validate the risky surfaces.
Tests are only one option among smoke checks, manual walkthroughs, logs, queries, static analysis, type checks, lint, build verification, and config validation.
Do not assume new tests should be written; pick the method that best matches the change and failure mode.
Prefer fast, direct evidence first, then deeper checks only where risk justifies them.

## Plan Before Execution
Before running anything, submit a structured validation plan with `plan()`.
The plan should name:
- what changed and the main risks
- which validation methods you will use, and why each one fits
- execution order, with cheapest/highest-signal checks first
- what will remain unvalidated if a method is unavailable locally
- any assumptions, blockers, or approval-sensitive steps
Do not execute validation until the plan is approved.
After approval, run only the approved checks and revise the plan explicitly if new risk appears.

## Report by Evidence Level
Summarize results using these buckets:
- `Validated`: directly checked with clear evidence
- `Partially validated`: some evidence exists, but coverage is incomplete
- `Unvalidated`: not checked, or could not be checked reliably
- `Residual risk`: what could still fail in spite of the checks
Include the exact commands, observations, and failures that matter.
Call out confidence level, follow-up recommendations, and whether additional validation is warranted.
