# Reviewing a Diff

`/diff` opens [hunk](https://github.com/modem-dev/hunk) beside your session and shows everything this branch has changed since it left the default branch: committed and uncommitted work, in one view. You annotate lines as you read; when you return to pi, your notes become line-anchored feedback the agent acts on.

## The review loop

1. Run `/diff`. hunk opens in a split pane beside your session.
2. Read the diff, and press `c` on any line to leave a note.
3. Return to pi and confirm. Your notes are sent to the agent, and the pane closes.

Your session pauses while you review. That is deliberate: hunk keeps notes in memory only, so they must be captured before its window closes. If a capture ever fails, `/diff` tells you and leaves the pane open rather than reporting an empty review.

## Reviewing what changed: `/diff last`

Each `/diff` marks a checkpoint at your current HEAD, and `/diff last` shows only what has moved since then. Review in passes instead of re-reading the whole branch each time.

- `/diff last` never advances the checkpoint, so running it twice shows the same span.
- With no checkpoint yet, or one a rebase has orphaned, it falls back to the full diff and says so.
- A checkpoint is a commit, so uncommitted work you already reviewed still appears in the next `/diff last`.

## Agent annotations

Agents annotate the same diff as they work, recording the reasoning behind their changes. Those notes appear in the diff at your next review, then clear once you have seen them.

## Requirements

`/diff` is primary-only and needs both Herdr and `hunk`. If either is missing, it reports what is and changes nothing.

For the internals behind checkpoints, annotation anchoring, and the sidecar model, see [Diff Surface Internals](../architecture/diff-surface.md).
