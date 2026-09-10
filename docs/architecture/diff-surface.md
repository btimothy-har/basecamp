# Diff Surface Internals

`/diff` opens [hunk](https://github.com/modem-dev/hunk) in a split Herdr pane, blocks the session while you review, and returns your inline annotations as line-anchored feedback. `annotate_changeset` lets the working agent put its own rationale beside the same diff. Basecamp launches and drives hunk; hunk renders and captures. Both are hard dependencies: without Herdr or hunk, `/diff` reports why and changes nothing.

## Checkpoints: `/diff` vs `/diff last`

Reviews are user-initiated checkpoints. Each completed `/diff` records the worktree's HEAD SHA, and `/diff last` shows only what moved since that point:

```
/diff        → full review vs merge-base; checkpoint := HEAD
…commits land…
/diff last   → what changed since that checkpoint
/diff        → full review; checkpoint moves up
```

`/diff last` never advances the checkpoint, so running it twice shows the same incremental diff. With no usable checkpoint it falls back to a full review (with a notice) and records one. Empty diffs run normally and still record. Checkpoints live in a `processScoped` map (`basecamp.diffCheckpoints`) keyed by worktree: they survive `/reload` but not a restart, since hunk sessions die with the process too.

A checkpoint is followed only when **both** guards hold:

| guard | catches |
|---|---|
| recorded merge-base still resolves | the base moved under the branch (fetch, rebase onto a new tip) |
| `last` is an ancestor of `HEAD` | sibling branches (which *share* a merge-base) and amend/rebase orphans |

Without the ancestry check, a sibling-branch checkpoint passes validation and `git diff <its-head>` renders that branch's commits as reversals.

**Accepted limitation:** the checkpoint is a commit SHA, and `hunk diff <sha>` includes the working tree, so uncommitted work already reviewed under a base `/diff` reappears in the next `/diff last`.

Two concurrent reviews of the same worktree are not supported; only one runs at a time per worktree, tracked by `OwnedReview`.

## Flow

```
<hunk-path> session list --json
herdr pane split $HERDR_PANE_ID --direction right --ratio 0.5 --cwd <worktree> \
                --no-focus --env HUNK_DISABLE_UPDATE_NOTICE=1
herdr pane run <pane_id> '<hunk-path>' 'diff' '<target>' ['--agent-context' '<sidecar>']
<hunk-path> session list --json
<hunk-path> session comment list <session-id> --type user --json
herdr pane close <pane_id>
```

The default target is `merge-base(detectDefaultBranch(), HEAD)` passed as a **single** argument. `hunk diff <target>` becomes `git diff --no-ext-diff --find-renames <target>`, so one view carries committed *and* uncommitted work; three-dot `main...HEAD` would show only commits. On the default branch the merge-base is HEAD, degrading to a working-tree diff with no special case. `/diff last` substitutes the recorded checkpoint SHA as the target; nothing else in the flow changes.

`<hunk-path>` is resolved once from Pi's inherited `PATH` to an absolute executable path. The version probe, pane launch, session discovery, and comment reads all use that path, rather than letting a fresh pane shell select a different installation. Shell startup files are not evaluated for resolution.

Session discovery is a preflight before any pane is replaced or opened. A failed CLI call or invalid session-list response is an error, not evidence that no sessions exist. The diagnostic includes the selected executable, version, and failure reason. This matters after upgrades: hunk 0.21's signed daemon authentication rejects a 0.20 client even though `--version` succeeds. Basecamp delegates authentication to hunk and does not switch installations or restart its daemon. After launch, polling tolerates transient daemon-startup failures through its retry window; if discovery still fails on the final attempt, that error is reported rather than a registration timeout.

hunk and herdr are pre-1.0 and host-installed, so the behaviour recorded here is observation of a moving target, not a contract.

## Why the session blocks

hunk keeps notes **in memory only**; sessions register over a socket and deregister when the window closes, so notes die with the window. The read has to happen while the session is alive, and blocking pi makes returning to pi the natural path rather than quitting hunk. This is a mitigation, not a guarantee: quitting hunk first still loses that review's notes. Notes are read on cancel as well as confirm, so text the user already wrote is not lost.

## Annotation lifecycle

The agent annotates **as it works**. Each `annotate_changeset` call merges into the per-worktree sidecar (same-path entries coalesce, duplicates collapse by key, a corrected rationale supersedes in place), and the next review renders everything accumulated. At review close the sidecar is **cleared**, but only when that review actually attached it: an unattached sidecar is left for a review that can show it. On any earlier failure (unread notes, unopened pane) nothing is consumed, so a retry sees the same span intact.

The anchor is **span identity, not a diff target**. Annotations are stamped with the review base, and a launch attaches the sidecar when that base still matches. Ranges are recorded against the *new* side of the diff (the working tree, whichever target is used), so rationale valid for an incremental view is valid in the full one.

Matching the launch target instead would break: the annotate-time anchor and a `/diff last` target are different quantities, so on a feature branch a full `/diff` would silently render nothing. Stamping the base keeps the anchor stable as commits land, letting calls accumulate rather than replace; a call with a different base replaces the files, because that rationale describes a span that is gone.

Each annotation carries a deterministic key (`sha256(path, range, summary, rationale)[:12]`), returned in the tool confirmation. `remove_annotation(key)` withdraws one (the case: annotate, revise the code above it, withdraw the mis-anchored note, re-annotate); removal prunes empty file entries and an emptied sidecar outright. An unknown key errors loudly, usually meaning a completed `/diff` already consumed it.

The rationale reaches the user only through the sidecar; the user's notes reach the agent as a **user message** (their own words, as if typed). Only annotations the user actually wrote are delivered; an empty review notifies and sends nothing.

## Why sidecars are launch-only

Agent annotations travel as hunk's `--agent-context` JSON sidecar rather than its live `comment apply` API: `comment apply` needs a pane that doesn't exist when an agent finishes, and anchors to a single `line` where the sidecar carries a `newRange`. So annotations *accumulate on disk* and render at the next `/diff`, never in a live session.

Sidecars are only ever passed at **launch**:

| | out-of-root sidecar path |
|---|---|
| launch | accepted |
| `hunk session reload` | refused: `Session reload refused agent context path outside the initial Hunk root` |

Putting the sidecar inside the root would satisfy reload, but not in a worktree: there `.git` is a *file* and the real gitdir lives under the main checkout, outside the worktree root, while anything in the working tree shows up as an untracked file in the diff. Worktrees are Basecamp's normal mode, so `/diff` never reloads; each invocation launches a fresh session, which also sidesteps the note-wipe below.

## Reload discards notes across scopes

Reloading a session to the **same** ref preserves its notes; reloading to a **different** ref destroys all of them, agent notes included, with no warning. `/diff` therefore replaces sessions rather than repointing them, and drains a leftover session's user notes before closing its pane.

Nonempty recovered notes are delivered immediately and finish that invocation; a new review requires another explicit `/diff`. Holding them through the next review would leave the only copy in an interrupted handler after their old pane closed. Delivering them and continuing would be unsafe too: `sendUserMessage` starts an agent turn even with `deliverAs: "followUp"` when idle, allowing edits while the next diff is open. A prior review with no notes can be replaced in the same invocation.

The pane id is `processScoped` (`basecamp.diffPanes`) because a hunk pane outlives the session that opened it; losing the id on `/reload` would strand a pane nothing can close. Until discovery succeeds, the same state retains the prelaunch session IDs. A retry can identify the one new session and read its notes before replacing it. Ambiguous candidates or legacy state without a baseline remain blocked rather than guessing ownership.

An absent daemon registration does not prove a TUI has no notes: it may be disconnected. An unidentified or disconnected review is left open until it reconnects or the user explicitly abandons its pane. Only Herdr's `pane_not_found` response permits forgetting such a review; other probe failures preserve it. Failure paths never report an empty review.

## `herdr pane run` is unescaped send-keys

`pane run` types its argument list into the target pane's shell and escapes nothing; `$HOME` expands and `a;touch x` executes. It also cannot re-launch into a pane already running a TUI, so closing is `herdr pane close`, never a sent `q`.

`runInHerdrPane` single-quotes every element, including the command name. Git refs legally contain `;`, `$`, `&`, and backticks, so this is a correctness requirement, not hardening. `/diff` accepts a **closed keyword set** (nothing, or `last`) parsed into a mode enum before anything runs; anything else errors without touching the shell. The SHAs that reach the argv are resolved by Basecamp from git, never parsed from the argument string.

`herdr pane split` splits the current session's pane (`$HERDR_PANE_ID`) rightward, so the diff appears side-by-side in the same tab. `pane split` has no `--label` flag, so the pane's terminal title comes from hunk.

## Annotation staleness

Ranges are recorded against the new side of the diff at call time and are not re-anchored afterwards, so editing an annotated file above an annotated range silently mis-anchors it. Mid-work annotation makes this a real risk; `remove_annotation` + re-annotate is the mitigation. hunk itself fails two ways on stale input, neither loudly: an annotation on a file absent from the changeset is **silently dropped**, and a range past EOF is kept but mis-anchored.

## Boundaries

Code review is untouched: `report_findings` and the `pi/code-review/annotate/` pane own review findings.
