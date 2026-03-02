---
name: pull-request
description: |
  Review branch changes and publish a pull request. This skill should be
  used when the user asks to "create a PR", "open a pull request", or
  when completed work needs publishing.
argument-hint: "[base-branch]"
disable-model-invocation: true
allowed-tools: Bash(gh pr create *), Bash(gh pr edit *)
hooks:
  PreToolUse:
    - matcher: Bash
      hooks:
        - type: command
          command: "${CLAUDE_PLUGIN_ROOT}/scripts/allow-pr-push.sh"
---

# Pull Request

Review branch changes, draft a description, and publish.

Use ${ARGUMENTS} as the base branch. Default to `main` if no argument provided.

PR descriptions are stored at `/tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md` and persist across sessions.

## Step 1: Review Changes

Fetch the base and diff the current branch against it.

```bash
git fetch origin $BASE
git log --oneline origin/$BASE..HEAD       # Commits on this branch
git diff --stat origin/$BASE...HEAD        # Changed files
git diff origin/$BASE...HEAD               # Full diff
```

Read the full diff. Identify scope, motivation, and key decisions. Search for related issues.

If the diff mixes unrelated concerns or is too large for a single review pass, stop and propose how to split the work into separate PRs before proceeding.

## Step 2: Verify Readiness

```bash
git status                                 # Clean working tree
git rebase origin/$BASE                    # Current with base
uv run pytest                              # Tests pass
uv run ruff check .                        # Lint clean
uv run ruff format --check .              # Format clean
```

Fix failures before proceeding.

## Step 3: Create PR

Check for an existing PR on this branch:

```bash
gh pr list --head $(git branch --show-current) --json number,title,url
```

If a PR exists, use its number. Fetch the current description from GitHub and write it to `/tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md`:

```bash
gh pr view $NUMBER --json title,body -q '.title + "\n\n" + .body' > /tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md
```

Edit from this file, then skip to Step 5.

Otherwise, verify the branch is pushed to origin:

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
```

If no upstream is set, ask the user to push the branch before continuing.

Then create an empty PR:

```bash
gh pr create --title "WIP" --body ""
```

Capture the PR number from the output.

## Step 4: Write Description

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

Write to `/tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md`. Line 1 is the title; remainder is the body.

Title format: `[Scope] Short summary` — scope = module/component/area, imperative mood, <70 chars.

Generate GitHub permalinks using the remote branch — `` [`path#L10`](url) ``.

## Step 5: Publish

Present the description to the user. Wait for approval — the user may edit the file before confirming.

After approval, update the PR:

```bash
TITLE=$(head -1 /tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md)
tail -n +2 /tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md > /tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER-body.md
gh pr edit $NUMBER --title "$TITLE" --body-file /tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER-body.md
```

Report the PR URL.

## Step 6: Update

For subsequent changes to the same PR, ask the user to push the latest commits.

If the description needs updating, edit `/tmp/claude-workspace/$BASECAMP_REPO/pull_requests/$NUMBER.md` and re-run Step 5.
