# Reviewing a Diff

`/diff` opens [hunk](https://github.com/modem-dev/hunk) in a split Herdr pane beside the session, showing everything the branch has changed since it left the default branch — committed and uncommitted work together, in one view. The session blocks while you read. Annotate any line with `c`, come back to pi, confirm, and your notes arrive as line-anchored feedback for the agent to act on. The pane closes behind you.

Each review is a checkpoint. `/diff` records where you finished, and `/diff last` shows only what moved since then — so you can review at intervals instead of re-reading the whole branch each time. `/diff last` never moves the checkpoint, so running it twice shows the same span; with no checkpoint yet (or one no longer in the branch's history, after a rebase) it falls back to the full diff and says so. Checkpoints are commits, so uncommitted work you already reviewed still appears in the next `/diff last`.

Blocking is deliberate: hunk keeps notes in memory only, so they have to be read while its window is still open. If the read fails, `/diff` says so and leaves the window up rather than reporting an empty review.

Agents annotate the same diff through the `annotate_changeset` tool, recording their rationale beside the code they changed as they work; it accumulates and renders at your next review, then clears once you have seen it. Each annotation gets a key the agent can pass to `remove_annotation` to withdraw one its later edits invalidated. Rationale is anchored to the branch's review base, so notes written for another branch never render against these lines.

`/diff` is primary-only and needs both Herdr and `hunk`; without them it reports what is missing and changes nothing.
