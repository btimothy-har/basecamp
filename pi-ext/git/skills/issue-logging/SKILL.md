---
name: issue-logging
description: "Log a GitHub issue: investigate a topic, check for duplicates, and draft a clear issue report."
---

# Issue Logging

Prepare a GitHub issue for user-reviewed publication. Work from any context already available: an active issue workflow handoff, the current conversation, code investigation, logs, docs, or the user's request.

## Context

Establish the issue context before drafting:

- Issue topic or problem statement
- Observed behavior and expected behavior
- Reproduction steps or concrete examples, when available
- Scope, impact, environment, and related context
- Draft path, when an active issue publish workflow provides one

If the current session already provided a topic and draft path, use them. Otherwise, investigate first and ask the user for missing essentials instead of inventing details.

## Publication Rule

`publish_issue` is the only path for creating the GitHub issue. Do not create or mutate GitHub issues through shell commands.

`publish_issue` requires active Basecamp issue workflow state and its draft path. If publication is requested but no active workflow or draft path exists, ask the user to start the publish workflow with `/create-issue <topic>` so Basecamp can allocate the draft path and enable reviewed publishing. You can still investigate and draft issue content before that workflow is active.

If `publish_issue` is not available in your tool list (for example in a subagent), do not try to publish via shell. Write the publishable issue draft to a temporary or scratch markdown file when file writes are available, and report the file path back to the parent/user. If an active draft path was explicitly provided for this workflow, use that path instead of inventing another one. If file writes are not available, include the draft in your response/report instead.

## Investigate

Understand the topic before drafting:

- Inspect relevant code, docs, tests, logs, or prior conversation context.
- Identify the user-facing problem, expected behavior, observed behavior, and likely scope.
- Collect concrete reproduction steps or examples when available.
- Note uncertainty explicitly instead of inventing details.

## Check GitHub Context

Search for related existing issues using read-only GitHub CLI operations only:

- Use `gh issue list --search "keywords" --state all`, or `gh issue ls` with appropriate keywords and `--state all`.
- Use `gh issue view <number>` to inspect likely matches.
- If an existing issue already covers the topic, stop and report the matching issue instead of drafting a duplicate.

If useful, check whether the repository has issue templates. GitHub commonly stores them under `.github/ISSUE_TEMPLATE/` or as issue template files in `.github/`. Read the relevant template before drafting.

## Draft the Issue

When a draft path is available, write the issue draft to exactly that path and nowhere else. If no draft path is available yet, keep the draft in the conversation or a scratch note until an issue publish workflow provides one.

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
- Include sections that fit the topic, such as summary, steps to reproduce, expected behavior, actual behavior, impact, environment, acceptance criteria, and related context.

## Submit for Review

When active issue publish workflow state and a draft path are available and `publish_issue` is available, call `publish_issue` with the draft path. If the user provides feedback, edit the same draft file and call `publish_issue` again. If `publish_issue` is unavailable, follow the fallback in the Publication Rule.
