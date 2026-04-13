---
name: gh-issue
description: Capture context as a GitHub issue. Enriches with code references, deduplicates against existing issues, and creates or comments as appropriate.
argument-hint: "<what to capture>"
disable-model-invocation: true
---

# Capture as GitHub Issue

Turn a discovery, decision, or observation into a trackable GitHub issue.

## Input

$ARGUMENTS

## Process

### 1. Build Context

From the input above and any relevant conversation context, extract:
- What was observed, discovered, or decided
- Relevant file paths, modules, or areas
- Why it matters or needs follow-up

Keep it focused — extract only what's relevant to the issue, not the full conversation.

### 2. Enrich

If the context references specific code, do a quick search (grep/find) to locate file paths and line numbers. If it doesn't reference code, skip this.

### 3. Search Existing Issues

```bash
gh issue list --search "{keywords}" --json number,title,state,url --limit 10
```

Categorize results:
- **Similar**: covers the same problem or request → do not create a duplicate.
- **Related**: touches the same area but is a distinct concern → include links in the new issue.

### 4. Act

**Do not create, apply, or modify labels.** Labels are managed by the user.

#### Similar issue exists

Comment on the existing issue with the new findings:

```bash
gh issue comment {number} --body "{new findings}"
```

Return the issue number and URL. Do not create a new issue.

#### No similar issue

Create a new issue. Title: concise, imperative mood. Body: brief — issues are reminders, not specifications. If related issues were found, include their links in the body.

```bash
gh issue create --title "{title}" --body "{body}"
```

### 5. Result

Return the issue number and URL.
