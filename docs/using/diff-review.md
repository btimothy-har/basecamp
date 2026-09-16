# Reviewing a Diff

## OMP `/diff`

`/diff` opens [Hunk](https://github.com/modem-dev/hunk) beside your OMP session. It freezes everything the current branch has changed since it left the default branch, including committed and uncommitted work, and reviews those exact bytes in one view.

Ordinary untracked files and symlinks are included. Untracked directories such as embedded repositories are reported and omitted while the rest of the diff remains reviewable; a path that disappears or becomes unreadable during capture is handled the same way. A tracked deletion followed by an untracked replacement at the same path appears once as the current working-tree addition.

### The review loop

1. Run `/diff`. Hunk opens in a split Herdr pane.
2. Read the diff and press `c` on any line to leave a note.
3. Return to OMP and confirm or cancel. Either choice captures notes already written before closing Hunk and saves a `diff-review` record; nonempty feedback is sent to the agent.

The OMP session pauses while you review because Hunk keeps live notes in memory. A failed note read is never treated as an empty review: the pane stays open and the agent annotation journal remains available for a later review. OMP does not reconnect to that Hunk session, so manually copy any user notes from the pane before closing it.

`/diff` takes no arguments. Each invocation is a fresh transaction over the full branch diff.

### Agent annotations

Agents can inspect and explain the same diff without Hunk:

- `read_diff` reads the full branch diff or selected repository-relative paths. It is available in primary sessions and subagents and reads each agent's own worktree.
- `annotate_diff` records rationale on a 1-based inclusive new-side line range for the next `/diff`.
- `remove_annotation` withdraws a recorded annotation by the ID returned from `annotate_diff`.

Annotations belong to the OMP session. They survive `/reload` and resume through OMP's transcript, while abandoned time-travel branches do not leak into the active one.

Anchoring is intentionally best-effort. Basecamp hashes the exact annotated lines when the annotation is recorded and checks that same numeric range against the frozen review immediately before opening Hunk. If the file, range, diff membership, or text changed, the annotation is discarded for that review instead of being remapped onto potentially unrelated code. `/diff` reports the discarded IDs.

A successfully captured review consumes annotations only through the session-journal position captured before Hunk opened. Any annotation recorded while the review is open remains available for the next `/diff`. A launch, session-discovery, note-read, or review-save failure consumes nothing and leaves the Hunk pane open. Indeterminate launch or discovery also retains the private frozen patch and agent context because Hunk may still start.

### Requirements

`/diff` is available only to the interactive session that owns the TUI and requires both Herdr and an installed `hunk`. `read_diff` does not require either program.

Basecamp resolves one absolute Hunk executable from OMP's inherited `PATH` and uses it for the version/capability probe, pane launch, process-bound session discovery, and note read. If you upgrade Hunk, restart OMP from a shell whose `PATH` selects the intended installation; `/reload` does not refresh the process environment.

For implementation details, see [Diff Surface Internals](../architecture/diff-surface.md).

## Legacy Pi `/diff`

Legacy Pi ships its own `/diff` implementation. It opens Hunk beside the Pi session and returns line-anchored feedback, but its state model and command surface differ from OMP.

### The review loop

1. Run `/diff`. Hunk opens in a split pane beside Pi.
2. Read the diff and press `c` on any line to leave a note.
3. Return to Pi and confirm. Your notes are sent to the agent and the pane closes.

Pi pauses while you review because Hunk keeps notes in memory. If capture fails, the pane stays open rather than reporting an empty review.

### Reviewing what changed: `/diff last`

Each full `/diff` marks a checkpoint at the current `HEAD`; `/diff last` shows only what moved since that checkpoint.

- `/diff last` never advances the checkpoint, so repeated calls show the same span.
- With no checkpoint, or one orphaned by a rebase, it falls back to the full diff and reports that fallback.
- A checkpoint is a commit, so previously reviewed uncommitted work still appears in the next `/diff last`.

### Agent annotations

Pi agents use `annotate_changeset` to accumulate rationale in a per-worktree sidecar. Those notes appear at the next review and clear only after a review that actually attached them completes. `remove_annotation` withdraws an entry by key.

### Requirements and recovery

Pi's `/diff` is primary-only and needs both Herdr and Hunk. It pins the Hunk installation found on Pi's inherited `PATH`; restart Pi from a fresh shell after upgrading Hunk because `/reload` does not refresh `PATH`.

Pi keeps checkpoint and pane ownership in process-scoped state, so both survive `/reload` but not process restart. For a transient discovery failure, leave the pane open and retry `/diff`: Pi attempts to reconnect, drain its notes, and close it before opening another review. If that review cannot reconnect and should be abandoned, close its pane explicitly.
