---
name: pull-request
description: "Prepare a pull request: review branch changes, verify readiness, and draft a clear PR title/body."
---

# Pull Request

Prepare a pull request for review. Start from whatever context is available: the user's request, the current conversation, the current branch, an existing PR, or handoff details already provided.

## Context

Establish the PR context before drafting:

- Current branch or PR branch
- Base branch
- PR number, when one is already known
- User review context, constraints, linked issues, or release notes

If the current session already provided these values, use them. Otherwise, derive what you can from git and read-only GitHub commands. If a required value is missing or ambiguous, ask the user instead of guessing.

## Publication Rule

`publish_pr` is the only agent path for updating the PR title and description. Do not update PR metadata through shell commands.

If `publish_pr` is unavailable or reports that no PR workflow is active, do not work around it. Save the drafted title/body to a temporary or scratch markdown file when your tools allow file writes, and report the file path back to the parent/user. If file writes are not available, include the draft title/body in your response/report instead.

If the user wants the PR published and the workflow is not active, ask them to start `/create-pr` in the primary session.

## Review Changes

Review the current branch against the base branch.

Use a shell variable or inline the actual base branch when running these commands:

```bash
git fetch origin "$BASE"
git log --oneline "origin/$BASE..HEAD"
git diff --stat "origin/$BASE...HEAD"
git diff "origin/$BASE...HEAD"
```

Read the full diff. Identify scope, motivation, and key decisions. Search for related issues.

If the diff mixes unrelated concerns or is too large for a single review pass, stop and propose how to split the work into separate PRs before proceeding.

## Verify Readiness

Call `git_status` before mutating local history. Confirm that:

- The current branch is the branch being prepared for the PR.
- The working tree is clean.
- Upstream/ahead/behind state matches the expected PR state.

If `git_status` reports uncommitted changes, stop and ask the user how to handle them before rebasing. Do not stash, discard, or fold them into the PR unless the user explicitly asks.

Rebase against the fetched base branch as part of this workflow:

```bash
git rebase "origin/$BASE"
```

Run the project's test and lint commands if they exist. Fix failures before proceeding.

If the rebase has conflicts, file paths shown by git are relative to the current working directory. Use `pwd` to get the absolute path and construct full paths when reading or editing conflicted files.

If the rebase replayed commits and rewrote history, stop and tell the user to force push manually. Do not attempt a force push.

## Draft the PR Description

Check the repo for a PR template. GitHub looks for templates in this order:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
find "$REPO_ROOT/.github" -maxdepth 2 -iname "pull_request_template*.md" 2>/dev/null
find "$REPO_ROOT" -maxdepth 1 -iname "pull_request_template*.md" 2>/dev/null
find "$REPO_ROOT/docs" -maxdepth 1 -iname "pull_request_template*.md" 2>/dev/null
```

If multiple templates exist, prefer `.github/PULL_REQUEST_TEMPLATE.md` over subdirectory variants.

If a template exists, read it using the absolute path returned by `find` with `cat` or the read tool. Otherwise, use this default:

```markdown
[Scope] Short summary

## What are you trying to accomplish?

What changed and why. Focus on impact, not implementation.

Closes #N

## What approach did you use?

### [Area]
- Change summary ([`path/file.py#L10-L25`](https://github.com/org/repo/blob/{hash}/path/file.py#L10-L25))

## How did you validate the changes?

- [ ] Tests pass
- [ ] Lint clean
- [ ] Manual verification: ...
```

**Title format**: `[Scope] Short summary` — scope = module/component/area, imperative mood, <70 chars.

Generate GitHub permalinks using the commit hash so links are stable across future pushes:

```bash
git rev-parse HEAD
gh repo view --json url -q .url
```

URL form: `{url}/blob/{hash}/{path}#L10-L25`, for example: ``[`path/file.py#L10-L25`](https://github.com/org/repo/blob/abc1234/path/file.py#L10-L25)``.

## Submit for Review

When `publish_pr` is available, call it with the drafted title and body. If the user provides feedback, revise the title/body and call `publish_pr` again. If `publish_pr` is unavailable or blocked, follow the fallback in the Publication Rule.
