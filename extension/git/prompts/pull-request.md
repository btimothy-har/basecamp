# Pull Request — PR #{{PR_NUMBER}}

Review branch changes and publish PR #{{PR_NUMBER}} against `{{BASE}}`.

## Step 1: Review Changes

Fetch the base and diff the current branch against it.

```bash
git fetch origin {{BASE}}
git log --oneline origin/{{BASE}}..HEAD
git diff --stat origin/{{BASE}}...HEAD
git diff origin/{{BASE}}...HEAD
```

Read the full diff. Identify scope, motivation, and key decisions. Search for related issues.

If the diff mixes unrelated concerns or is too large for a single review pass, stop and propose how to split the work into separate PRs before proceeding.

## Step 2: Verify Readiness

```bash
git status
git rebase origin/{{BASE}}
```

Run the project's test and lint commands if they exist. Fix failures before proceeding.

## Step 3: Write Description

Check the repo for a PR template:

```bash
find . -maxdepth 2 -iname "pull_request_template*" -not -path "./.git/*" 2>/dev/null
```

If a template exists, use it as the base structure. Otherwise, use this default:

```markdown
[Scope] Short summary

## What are you trying to accomplish?

What changed and why. Focus on impact, not implementation.

Closes #N

## What approach did you use?

### [Area]
- Change summary ([`path/file.py#L10-L25`](permalink))

## How did you validate the changes?

- [ ] Tests pass
- [ ] Lint clean
- [ ] Manual verification: ...
```

Write to `/tmp/basecamp/pull_requests/{{PR_NUMBER}}.md`. Line 1 is the title; remainder is the body.

Title format: `[Scope] Short summary` — scope = module/component/area, imperative mood, <70 chars.

Generate GitHub permalinks using the remote branch — `` [`path#L10`](url) ``.

## Step 4: Publish

Present the description to the user. Wait for approval — the user may edit the file before confirming.

After approval, update the PR:

```bash
mkdir -p /tmp/basecamp/pull_requests
TITLE=$(head -1 /tmp/basecamp/pull_requests/{{PR_NUMBER}}.md)
tail -n +2 /tmp/basecamp/pull_requests/{{PR_NUMBER}}.md > /tmp/basecamp/pull_requests/{{PR_NUMBER}}-body.md
gh pr edit {{PR_NUMBER}} --title "$TITLE" --body-file /tmp/basecamp/pull_requests/{{PR_NUMBER}}-body.md
```

Report the PR URL.

## Step 5: Update

For subsequent changes to the same PR, ask the user to push the latest commits.

If the description needs updating, edit `/tmp/basecamp/pull_requests/{{PR_NUMBER}}.md` and re-run Step 4.
