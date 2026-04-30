---
name: create-pr
description: "Use for the /create-pr pull request workflow: review branch changes, verify readiness, draft a PR title/body, and publish through pr_publish."
---

# Create PR

## Runtime Context

This skill is intended for the `/create-pr` workflow. The command message supplies the runtime context for the workflow, including the PR number, the base branch, and any additional user context or constraints.

Use the exact runtime context supplied by `/create-pr` wherever this workflow needs those values. If required context is missing, conflicting, or ambiguous, stop and ask the user instead of guessing.

## Step 1: Review Changes

Review the branch changes for the PR identified in the runtime context and prepare to publish it against the supplied base branch.

Fetch the base branch and diff the current branch against it. For shell commands, set `BASE` to the base branch supplied by `/create-pr` before running the commands:

```bash
git fetch origin "$BASE"
git log --oneline "origin/$BASE..HEAD"
git diff --stat "origin/$BASE...HEAD"
git diff "origin/$BASE...HEAD"
```

Read the full diff. Identify scope, motivation, and key decisions. Search for related issues.

If the diff mixes unrelated concerns or is too large for a single review pass, stop and propose how to split the work into separate PRs before proceeding.

## Step 2: Verify Readiness

Call `git_status` before mutating local history. Confirm that:

- The current branch is the PR branch identified by the runtime context.
- The working tree is clean.
- Upstream/ahead/behind state matches the expected PR state.

If `git_status` reports uncommitted changes, stop and ask the user how to handle them before rebasing. Do not stash, discard, or fold them into the PR unless the user explicitly asks.

Rebase against the fetched base branch as part of this workflow, using the base branch from the runtime context:

```bash
git rebase "origin/$BASE"
```

Run the project's test and lint commands if they exist. Fix failures before proceeding.

If the rebase has conflicts, file paths shown by git are relative to the current working directory. Use `pwd` to get the absolute path and construct full paths when reading or editing conflicted files.

If the rebase replayed commits and rewrote history, stop and tell the user to force push manually. Do not attempt a force push.

## Step 3: Write and Publish

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

Draft the title and body, then call `pr_publish` with them. Do not publish the PR description through shell commands; publication must go through `pr_publish` so the user can review before GitHub is updated.
