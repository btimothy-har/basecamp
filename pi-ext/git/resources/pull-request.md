# Pull Request — PR #{{PR_NUMBER}}

Review branch changes and publish PR #{{PR_NUMBER}} against `{{BASE}}`.{{CONTEXT}}

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

If the rebase has conflicts, file paths shown by git are relative to the current working directory. Use `pwd` to get the absolute path and construct full paths when reading or editing conflicted files.

If the rebase replayed commits (history rewritten), stop and tell the user to force push manually — do not attempt force push.

## Step 3: Write and Publish

Check the repo for a PR template. GitHub looks for templates in this order:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
find "$REPO_ROOT/.github" -maxdepth 2 -iname "pull_request_template*.md" 2>/dev/null
find "$REPO_ROOT" -maxdepth 1 -iname "pull_request_template*.md" 2>/dev/null
find "$REPO_ROOT/docs" -maxdepth 1 -iname "pull_request_template*.md" 2>/dev/null
```

If multiple templates exist, prefer `.github/PULL_REQUEST_TEMPLATE.md` over subdirectory variants.

If a template exists, read it using the absolute path returned by `find` (via `cat <path>` or the read tool). Otherwise, use this default:

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

Generate GitHub permalinks using the commit hash (true permalinks, stable across future pushes):

```bash
git rev-parse HEAD          # commit hash
gh repo view --json url -q .url  # repo base URL
```

URL form: `{url}/blob/{hash}/{path}#L10-L25` — e.g. `` [`path/file.py#L10-L25`](https://github.com/org/repo/blob/abc1234/path/file.py#L10-L25) ``.

Draft the title and body, then call `pr_publish` with them. The user reviews in a read-only overlay and can:

- **Publish** (Enter) — publishes directly
- **Feedback** (Tab → type → Enter) — returns feedback for you to revise and call `pr_publish` again
- **Cancel** (Esc) — ask the user what they want to change

## Updating

For subsequent changes, invoke `/pull-request` again — it handles pushing and then call `pr_publish` with the updated description.
