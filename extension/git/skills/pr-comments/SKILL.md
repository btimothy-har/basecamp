---
name: pr-comments
description: |
  Synthesize review findings and post as GitHub PR comments. This skill
  should be used when the user asks to "post comments", "publish review",
  "comment on the PR", or when review findings need posting to GitHub.
disable-model-invocation: true
---

# PR Comments

Synthesize review findings from the conversation, draft them into a comment file, and post to the PR after user review.

Comments are stored at `${BASECAMP_WORK_DIR}/pr-comments/{number}.md` and persist across sessions.

## Prerequisite

Before proceeding, verify that the conversation contains review findings — output from review skills, walkthrough observations, manual analysis, or user-provided feedback. If no findings exist, stop and ask the user what they'd like to review or comment on.

## Step 1: Synthesize Findings

Read back through the conversation and extract all actionable findings from:
- Review skill output (security-review, test-review, code-documentation, etc.)
- Walkthrough observations and discussion points
- Manual analysis or user-provided feedback
- Code issues surfaced during the conversation

For each finding, identify: file path, line number (if applicable), severity, and description.

## Step 2: Compile Draft

Write findings to `${BASECAMP_WORK_DIR}/pr-comments/{number}.md`:

```markdown
# PR Comments — #123

## Summary
Overall assessment of the PR. Key themes, patterns observed,
and high-level feedback.

## src/api/auth.py

### Line 42 — 🔴 SQL injection via unsanitized input
User-provided `username` passed directly to query without sanitization.

**Suggestion**: Use parameterized query:
`cursor.execute("SELECT * FROM users WHERE name = ?", (username,))`

### Lines 40-45 — 🟡 Missing error context
Exception handler swallows original traceback.

**Suggestion**: Chain the exception with `raise NewError(...) from e`.

## src/utils/cache.py

### Line 15 — 🟠 Unbounded cache growth
No eviction policy on in-memory cache. Will grow indefinitely under load.

**Suggestion**: Add `maxsize` parameter or TTL-based eviction.

## General
- Consider adding integration tests for the auth flow.
- Nice separation of concerns in the new middleware layer.
```

**Format rules:**
- `## Summary` — overall assessment (becomes review body or standalone PR comment)
- `## file/path` — file-level grouping (H2)
- `### Line N — severity title` — line comment (H3), where N is the diff line number
- `### Lines N-M — severity title` — multi-line range comment
- Body text below each H3 is the comment content
- `## General` — observations not tied to specific lines (appended to summary when posting)
- Severity indicators: 🔴 blocker, 🟠 major, 🟡 minor, 🟢 nitpick

## Step 3: Human Review

Present the draft to the user. The user may edit the file to:
- Remove comments they don't want to post
- Modify comment text or severity
- Remove entire file sections
- Add additional comments

Ask the user to confirm they are ready and choose a publish mode:

- **As review** — all comments bundled into a single GitHub review with a verdict (APPROVE / REQUEST_CHANGES / COMMENT)
- **As comments** — comments posted individually, no formal review verdict

## Step 4: Publish

### Setup

```bash
COMMIT_SHA=$(gh pr view {number} --json headRefOid -q '.headRefOid')
REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
OWNER=$(echo "$REPO" | cut -d/ -f1)
REPO_NAME=$(echo "$REPO" | cut -d/ -f2)
```

### As Review (bundled)

Submit all comments as a single review. Build a JSON payload with the summary as review body, inline comments as the comments array, and the user's chosen verdict as the event.

```bash
gh api repos/$OWNER/$REPO_NAME/pulls/{number}/reviews \
  --input payload.json
```

Payload structure:
```json
{
  "body": "Summary text here...",
  "event": "COMMENT",
  "comments": [
    {
      "path": "src/api/auth.py",
      "line": 42,
      "side": "RIGHT",
      "body": "🔴 **SQL injection via unsanitized input**\n\nUser-provided `username` passed directly..."
    }
  ]
}
```

For multi-line comments, add `start_line` and `start_side` fields.

Post `## General` items by appending them to the review body.

### As Comments (individual)

**Line-level comment:**
```bash
gh api repos/$OWNER/$REPO_NAME/pulls/{number}/comments \
  -f body="Comment text" \
  -f path="src/api/auth.py" \
  -f commit_id="$COMMIT_SHA" \
  -F line=42 \
  -f side="RIGHT"
```

**Multi-line range comment:**
```bash
gh api repos/$OWNER/$REPO_NAME/pulls/{number}/comments \
  -f body="Comment text" \
  -f path="src/api/auth.py" \
  -f commit_id="$COMMIT_SHA" \
  -F start_line=40 \
  -F line=45 \
  -f start_side="RIGHT" \
  -f side="RIGHT"
```

**File-level comment** (no specific line):
```bash
gh api repos/$OWNER/$REPO_NAME/pulls/{number}/comments \
  -f body="Comment text" \
  -f path="src/api/auth.py" \
  -f commit_id="$COMMIT_SHA" \
  -f subject_type="file"
```

**Summary and general comments:**
```bash
gh pr comment {number} --body "Summary and general observations"
```

### Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| 404 on line comment | Line not in diff | Fall back to file-level comment with line reference in body |
| 422 unprocessable | Invalid line number | Verify line exists in the diff with `gh pr diff` |
| 401 unauthorized | Auth issue | Check `gh auth status` |

If a line comment fails, fall back to a file-level comment and include the intended line number in the body text.

### Clean Up

After all comments are posted:
1. Delete `${BASECAMP_WORK_DIR}/pr-comments/{number}.md`
2. Report summary: total posted, any failures, any fallbacks