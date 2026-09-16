# Diff Surface Internals

## OMP `/diff`

`omp/diff` owns Basecamp's OMP-native diff surface. `/diff` opens [Hunk](https://github.com/modem-dev/hunk) in a disposable Herdr pane, blocks OMP while the user reviews, captures inline notes before closing the pane, and persists the result as a `diff-review`. `read_diff`, `annotate_diff`, and `remove_annotation` give agents a local, Hunk-independent interface to the same diff.

The legacy Pi implementation remains separate. OMP code imports only OMP APIs and native VCS primitives, never executable modules from `pi/`.

### Shared diff scope

The command and `read_diff` share one loader:

1. discover the repository and default branch;
2. resolve `HEAD`;
3. compute `merge-base(defaultBranch, HEAD)`;
4. call OMP's native `diffText({ base, files? })` for committed, staged, and unstaged changes;
5. enumerate nonignored untracked paths in the same optional scope, append a native no-index patch for each ordinary file or symlink in stable path order, and report untracked directories that cannot be represented as one file.

The merge-base is passed as one target, so tracked changes include both branch commits and the current index/working tree. On the default branch it naturally becomes a working-tree diff. Appending untracked file patches completes the review surface without staging files or shelling out. An embedded repository or other untracked directory is reported and omitted rather than aborting the remaining diff. If Git reports both a tracked deletion and an untracked file at the same path, the loader coalesces them into the current working-tree addition instead of displaying two contradictory file sections. `read_diff` may restrict all sources to validated repository-relative paths; `/diff` always reviews the whole frozen snapshot.

Agents read this snapshot locally. Hunk is not an agent API, and no MCP or persistent companion process participates.

### Session annotation journal

`annotate_diff` stores complete `DiffAnnotation` payloads as OMP CustomEntries under `basecamp.diff.annotation`. The payload lives directly in the JSONL entry rather than pointing through an artifact. Tool-call history is not authoritative because OMP may prune model context; CustomEntries are persisted extension state and omitted from model context.

The journal has three events:

- `recorded`: one tool call's annotation batch;
- `withdrawn`: IDs removed by `remove_annotation`;
- `diff-completed`: the artifact reference and captured journal cutoff for a successfully captured review.

Current annotations are derived from `sessionManager.getBranch()` after the later of the last `reset_boundary` and the entry referenced by the latest valid `diff-completed` event. `/diff` captures the active branch leaf before launch and records that ID as its cutoff after success. Annotations appended while Hunk is open therefore remain active for the next review. OMP's existing branch and time-travel semantics stay the ownership model: annotations survive `/reload` and resume, while entries on abandoned branches do not participate.

Each annotation has a deterministic ID over repository, path, range, summary, and rationale. Its anchor is a separate hash over the repository-relative path, 1-based inclusive new-side range, and exact lines parsed from the frozen patch.

Immediately before `/diff` launches Hunk, Basecamp validates that:

- the annotation belongs to the loaded repository;
- the file and numeric range still exist;
- the range still falls within one displayed new-side hunk;
- the exact-range hash still matches.

Failures are discarded for that review and reported by ID. There is deliberately no search, remapping, source snapshot, or rewind mechanism: best-effort omission is safer than attaching rationale to different code.

### Transaction flow

```text
pin the owning OMP session and load the merge-base diff
resolve one absolute hunk executable and probe its version and patch/agent-note capabilities
hunk session list --json
fold the annotation journal, capture its branch cutoff, and validate annotations
write private temporary patch and --agent-context files
herdr pane split <current-pane> --direction right --ratio 0.5 --no-focus
herdr pane run <new-pane> '<hunk>' 'patch' '<patch-file>' ['--agent-context' '<context-file>' '--agent-notes']
poll herdr pane process-info for processes carrying the exact frozen patch path
poll hunk session list --json for exactly one new session with that PID
remove the temporary launch files
block OMP while the user reviews
hunk session comment list <session-id> --type user --json
verify the OMP session still owns the transaction and persist the diff-review
herdr pane close <new-pane>
append diff-completed through the captured journal cutoff
deliver nonempty notes as a user message
```

The temporary patch freezes the exact bytes returned by the shared loader, so later working-tree movement cannot make Hunk display a different diff from the one Basecamp validated. The optional agent-context JSON contains only annotations that passed that validation, and `--agent-notes` makes Hunk show them. Both files are private (`0700` directory, `0600` files), removed once Hunk has registered the session, and never treated as state.

The `diff-review` artifact records the repository, base and head revisions, hash of the frozen patch, submitted/cancelled status, user notes, displayed agent annotation IDs, and discarded agent annotation IDs. With no session artifact directory, OMP's content-addressed blob store provides the readable fallback.

### Failure invariants

Hunk notes live in the running session, so ordering is load-bearing:

- session-list preflight succeeds before Basecamp opens a pane;
- the launched Hunk session is bound to the exact Herdr pane process rather than guessed from repository or timing alone;
- cancel and confirm both read notes;
- notes are read while Hunk is still alive;
- process binding, session discovery, note-read, or artifact-save failure leaves the pane open and appends no completion boundary;
- failed reads are never represented as zero notes;
- only a persisted review in the same originating OMP session appends `diff-completed`;
- empty successful reviews notify but do not manufacture a user turn.

The command identifies its Hunk session by comparing a prelaunch session set with the postlaunch list, then requiring the new session's PID to match a process in the exact Herdr pane whose argv carries the unique frozen patch path. It re-reads that pane process set on every session poll so an npm launcher can spawn the child that ultimately registers with Hunk. Zero matching sessions time out; multiple matches are ambiguous and fail closed. One absolute Hunk path is still pinned for the probe and launch so a fresh pane shell cannot select another installation.

### Herdr shell boundary

`herdr pane run` types arguments into a pane shell rather than executing an argv directly. Every element is therefore single-quoted independently, including the executable and temporary patch/context paths. `/diff` accepts no arguments and rejects unexpected text before any shell call.

`/diff` is gated to an interactive primary Herdr session. `read_diff` remains available to subagents because it reads their isolated cwd/worktree and has no UI or cross-session state.

### Boundaries

Native OMP `/review` remains the code-review surface. `/diff` is the user's direct Hunk annotation loop; it does not replace reviewer fan-out or `review_findings`.

## Legacy Pi `/diff`

Legacy Pi's separately registered `pi/diff` domain retains its checkpoint, sidecar, and process-scoped pane-recovery model. Its `/diff` opens Hunk in a split Herdr pane, blocks Pi while the user reviews, and returns inline annotations as line-anchored feedback. `annotate_changeset` puts the working agent's rationale beside the same diff.

### Checkpoints: `/diff` vs `/diff last`

Each completed full `/diff` records the worktree's `HEAD`; `/diff last` shows only what moved since that checkpoint:

```text
/diff        → full review vs merge-base; checkpoint := HEAD
…commits land…
/diff last   → what changed since that checkpoint
/diff        → full review; checkpoint moves up
```

`/diff last` never advances the checkpoint. With no usable checkpoint it falls back to a full review, reports the fallback, and records one. Empty diffs still record. Checkpoints live in the process-scoped `basecamp.diffCheckpoints` map keyed by worktree, so they survive `/reload` but not process restart.

A checkpoint is followed only when both guards hold:

| guard | catches |
|---|---|
| recorded merge-base still resolves | default-branch movement after fetch or rebase |
| `last` is an ancestor of `HEAD` | sibling branches, amend, and rebase orphans |

Without the ancestry check, a checkpoint from a sibling branch can pass merge-base validation and render that branch's commits as reversals.

The checkpoint is a commit SHA, while `hunk diff <sha>` also includes the working tree. Previously reviewed uncommitted work therefore reappears in the next `/diff last`.

Only one review runs per worktree, tracked by `OwnedReview`.

### Flow

```text
<hunk-path> session list --json
herdr pane split $HERDR_PANE_ID --direction right --ratio 0.5 --cwd <worktree> \
                --no-focus --env HUNK_DISABLE_UPDATE_NOTICE=1
herdr pane run <pane-id> '<hunk-path>' 'diff' '<target>' ['--agent-context' '<sidecar>']
<hunk-path> session list --json
<hunk-path> session comment list <session-id> --type user --json
herdr pane close <pane-id>
```

The default target is `merge-base(detectDefaultBranch(), HEAD)` passed as one argument. `hunk diff <target>` becomes a single Git diff from that target through the working tree, so committed and uncommitted work appear together. `/diff last` substitutes the recorded checkpoint SHA.

Pi resolves one absolute Hunk executable from its inherited `PATH` and uses it for the version probe, pane launch, session discovery, and comment reads. A failed preflight or malformed session-list response is an error, not evidence that no sessions exist. Polling after launch tolerates transient daemon startup, but the final failure is reported.

Hunk and Herdr are pre-1.0 host dependencies, so these behaviors are observations of a moving integration surface rather than stable external contracts.

### Why the session blocks

Hunk notes live in memory and disappear when the window closes. Pi must read them while the session is alive, and blocking makes returning to Pi the natural handoff. Cancel and confirm both read notes so text the user already wrote is not lost.

### Annotation lifecycle

Each `annotate_changeset` call merges into a per-worktree sidecar: same-path entries coalesce, duplicate keys collapse, and corrected rationale supersedes in place. The next review renders the accumulated rationale. Review close clears only a sidecar that review actually attached; an earlier launch or note-read failure consumes nothing.

Annotations are stamped with the review base and address 1-based inclusive ranges on the new side. Matching the launch target instead would break because the annotate-time base and `/diff last` target are different quantities.

Each entry carries a deterministic key over path, range, summary, and rationale. `remove_annotation(key)` withdraws it, pruning empty file entries and deleting an emptied sidecar. The user's notes return as a user message; an empty review only notifies.

### Why sidecars are launch-only

Pi uses Hunk's `--agent-context` JSON rather than live `comment apply`: agents normally finish before a pane exists, and the sidecar supports a `newRange` rather than a single line.

Sidecars are passed only at launch:

| | out-of-root sidecar path |
|---|---|
| launch | accepted |
| `hunk session reload` | refused |

Putting the sidecar inside a worktree would expose an untracked file in the diff; the worktree's `.git` is itself a file whose real gitdir sits outside the root. Pi therefore launches a fresh Hunk session rather than reloading one with agent context.

### Reload and pane recovery

Reloading Hunk to the same ref preserves notes, while reloading to a different ref destroys user and agent notes without warning. Pi replaces sessions instead of repointing them and drains an owned leftover session before closing it.

Recovered nonempty notes are delivered immediately and end that `/diff` invocation. Continuing into another review would allow a follow-up agent turn to edit while the new diff is open.

Pane ownership lives in the process-scoped `basecamp.diffPanes` map because a Hunk pane can outlive the Pi session that created it. Until discovery succeeds, the same state retains the prelaunch session IDs. A retry can identify the one new session, read its notes, and replace it. Ambiguous candidates or legacy state without a baseline fail closed.

An absent daemon registration does not prove a pane has no notes because the TUI may be disconnected. An unidentified or disconnected review remains owned until it reconnects or the user explicitly abandons the pane. Only Herdr's `pane_not_found` permits Pi to forget it.

### Herdr shell boundary

`herdr pane run` sends text to a pane shell and escapes nothing. Pi single-quotes every argument independently, including the executable. Its `/diff` accepts the closed keyword set of no argument or `last`; anything else is rejected before a shell call, and every target SHA is resolved from Git rather than parsed from user text.

### Annotation staleness

Legacy Pi does not re-anchor annotations after edits above a recorded range. `remove_annotation` followed by a fresh `annotate_changeset` is the mitigation. Hunk otherwise silently drops annotations for files absent from the diff and can mis-anchor ranges past end-of-file.

### Boundaries

Legacy code review remains separate: `report_findings` and `pi/code-review/annotate/` own review findings.
