---
name: issue-logging
description: "Log a GitHub issue: investigate a topic, check for duplicates, and draft a clear issue report."
---

# Issue Logging

Prepare a GitHub issue for review. Describe the problem to be solved, not the solution to implement. Start from whatever context is available: the user's request, the current conversation, code investigation, logs, docs, or handoff details already provided.

## Context

Establish the issue context before drafting:

- Issue topic or problem statement
- Observed behavior and expected behavior
- Reproduction steps or concrete examples, when available
- Scope, impact, environment, evidence, and related context
- Draft path, if one is already provided

If the current session already provided a topic and draft path, use them. Otherwise, investigate first and ask the user for missing essentials instead of inventing details.

## Publication Rule

`publish_issue` is the only agent path for creating the GitHub issue. Do not create or mutate GitHub issues through shell commands.

If `publish_issue` is unavailable or reports that no issue workflow/draft path is active, do not work around it. If a draft path was provided, write the publishable issue draft there. Otherwise, save it to a temporary or scratch markdown file when your tools allow file writes, and report the file path back to the parent/user. If file writes are not available, include the draft in your response/report instead.

If the user wants the issue published and the workflow is not active, ask them to start `/create-issue <topic>` in the primary session.

## Investigate

Understand the problem before drafting:

- Inspect relevant code, docs, tests, logs, or prior conversation context.
- Identify the user-facing problem, expected behavior, observed behavior, and likely scope.
- Collect concrete reproduction steps, examples, error messages, or affected paths when available.
- Separate evidence from hypotheses; label uncertainty explicitly instead of inventing details.
- Avoid prescribing the implementation. Mention possible causes or solution ideas only when they are factual context, explicitly requested, or clearly labeled as non-binding.

## Check GitHub Context

Search for related existing issues using read-only GitHub CLI operations only:

- Use `gh issue list --search "keywords" --state all`, or `gh issue ls` with appropriate keywords and `--state all`.
- Use `gh issue view <number>` to inspect likely matches.
- If an existing issue already covers the topic, stop and report the matching issue instead of drafting a duplicate.

If useful, check whether the repository has issue templates. GitHub commonly stores them under `.github/ISSUE_TEMPLATE/` or as issue template files in `.github/`. Read the relevant template before drafting.

## Draft the Issue

When a draft path is available, write the issue draft to exactly that path and nowhere else. If no draft path is available yet, keep the draft in the conversation or save it to a temporary/scratch markdown file when your tools allow file writes.

Use this markdown contract for the publishable draft:

```markdown
# Issue title

Issue body in GitHub-flavored markdown.
```

Rules:

- The first non-empty line must be a single H1 heading (`# Issue title`).
- The heading text is the issue title.
- All remaining content is the issue body.
- Do not include frontmatter or wrapper text outside the issue draft.
- Follow the repository's issue template when one applies.
- Frame the issue around the problem, evidence, impact, and desired behavior.
- Do not mandate implementation details, architecture, libraries, or specific code changes unless the user explicitly asked for that solution.
- Include sections that fit the topic, such as summary, steps to reproduce, expected behavior, actual behavior, impact, environment, evidence, related context, and outcome-focused acceptance criteria.

## Submit for Review

When `publish_issue` is available and a draft path is ready, call `publish_issue` with the draft path. If the user provides feedback, edit the same draft file and call `publish_issue` again. If `publish_issue` is unavailable or blocked, follow the fallback in the Publication Rule.
