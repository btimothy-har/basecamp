---
name: pr
description: "Create or update a GitHub pull request from the current branch with the gh CLI. Use when the user asks to open, create, raise, update, or push a PR / pull request. Opens as a draft, writes a title and body from the diff, and reuses the existing PR for the branch if one is already open."
---

# Pull Request

Create or update a GitHub pull request for the current branch using the `gh` CLI. The same flow handles both cases: if a PR already exists for the branch, update it in place; otherwise open a new draft.

## When to Use

Trigger on requests to open, create, raise, submit, update, or push a pull request. If the user gave extra context (what to emphasize, a linked issue, reviewers), fold it into the title and body.

## 1. Resolve the Base Branch

Default the base to the remote's default branch; fall back to `main`:

```bash
base=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
base=${base:-main}
```

If the user named a base branch explicitly, use theirs instead.

## 2. Inspect State

Understand what you're proposing before you write anything:

```bash
git branch --show-current              # the head branch
git status --short                     # uncommitted work?
git log --oneline "$base"..HEAD        # commits that will be in the PR
git diff "$base"...HEAD --stat         # shape of the change
```

Commit or surface uncommitted changes as appropriate — don't silently leave work out of the PR. If the branch equals the base branch, stop and tell the user: there's nothing to open a PR from.

## 3. Push the Branch

Ensure the branch is on the remote with an upstream set:

```bash
git push -u origin HEAD
```

## 4. Create or Update

Check whether a PR already exists for this branch, then branch on the result:

```bash
gh pr view --json number,url,state 2>/dev/null
```

- **Exists** → update it: `gh pr edit` to refresh the title/body (and any other fields the user asked for).
- **None** → create a draft against the base:

  ```bash
  gh pr create --draft --base "$base" --title "<title>" --body "<body>"
  ```

Open as a **draft** by default. Only create a ready-for-review PR if the user explicitly asks for one.

## 5. Write a Clear Title and Body

Base the title and body on the actual diff and commits, not guesses.

- **Title** — concise, imperative summary of the change (e.g. "Add retry backoff to the hub connector").
- **Body** — what changed and why, the key decisions or trade-offs, and anything a reviewer needs to verify it. Reference a linked issue when there is one.

Before writing the body, check for a PR template and follow its structure if present:

```bash
ls .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md \
   .github/PULL_REQUEST_TEMPLATE/*.md docs/PULL_REQUEST_TEMPLATE.md 2>/dev/null
```

Populate the template's sections from your changes; skip any section that asks for credentials, tokens, or internal secrets.

## 6. Summarize

Report back the PR number and URL, whether the branch was pushed, and whether it was created or updated. If CI or review follow-up matters to the user, offer it as a next step rather than assuming it.
