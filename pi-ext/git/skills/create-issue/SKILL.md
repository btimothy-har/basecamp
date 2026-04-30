---
name: create-issue
description: "Use for the /create-issue workflow: investigate a topic, draft a GitHub issue at the supplied draft path, and publish through issue_publish."
---

# Create Issue

## Runtime Context

This skill is intended for the `/create-issue` workflow. The command message supplies the runtime context for the workflow, including the issue topic, the draft path, and any additional user context or constraints.

Use the exact runtime context supplied by `/create-issue` wherever this workflow needs those values. If the topic or draft path is missing, conflicting, or ambiguous, stop and ask the user instead of guessing. Write the draft only to the draft path supplied by `/create-issue`.

## Step 1: Investigate

Understand the topic before drafting:

- Inspect relevant code, docs, tests, logs, or prior conversation context.
- Identify the user-facing problem, expected behavior, observed behavior, and likely scope.
- Collect concrete reproduction steps or examples when available.
- Note uncertainty explicitly instead of inventing details.

## Step 2: Check GitHub Context

Search for related existing issues using read-only GitHub CLI operations only:

- Use `gh issue list --search "keywords" --state all`, or `gh issue ls` with appropriate keywords and `--state all`.
- Use `gh issue view <number>` to inspect likely matches.
- If an existing issue already covers the topic, stop and report the matching issue instead of drafting a duplicate.

If useful, check whether the repository has issue templates. GitHub commonly stores them under `.github/ISSUE_TEMPLATE/` or as issue template files in `.github/`. Read the relevant template before drafting.

## Step 3: Write the Draft

Write the issue draft to exactly the draft path supplied by `/create-issue` and nowhere else.

Use this markdown contract:

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

## Step 4: Publish Through Review

After writing the draft, call `issue_publish` with the same draft path supplied by `/create-issue`.

Do not directly create or mutate GitHub issues from the shell. Publication must go through `issue_publish` so the user can review before anything is posted.
