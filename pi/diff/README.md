# diff

Basecamp's diff/review surface, filling the gap left when Companion was retired: `/diff` opens [hunk](https://github.com/modem-dev/hunk) in a split Herdr pane, blocks the session while you review, and returns your inline annotations as line-anchored feedback. `annotate_changeset` lets the working agent put its own rationale beside the same diff.

Basecamp launches and drives hunk; hunk renders and captures. Both are hard dependencies — absent Herdr or hunk, `/diff` reports why and changes nothing.

## Checkpoints: `/diff` vs `/diff last`

Reviews are user-initiated checkpoints. Each completed `/diff` records the worktree's HEAD SHA, and `/diff last` shows only what moved since that point:

```
/diff        → full review vs merge-base; checkpoint := HEAD
…commits land…
/diff last   → what changed since that checkpoint
/diff        → full review; checkpoint moves up
```

`/diff last` never advances the checkpoint — it is a second look at the same span, so running it twice shows the same incremental diff. With no usable checkpoint it falls back to a full review (with a notice) and records one. Empty diffs run normally and still record.

Checkpoints live in a `processScoped` map (`basecamp.diffCheckpoints`) keyed by worktree: they survive `/reload` but not a restart — deliberately, since hunk sessions die with the process too.

A checkpoint is followed only when **both** guards hold, because either alone is insufficient:

| guard | catches |
|---|---|
| recorded merge-base still resolves | the base moved under the branch (fetch, rebase onto a new tip) |
| `last` is an ancestor of `HEAD` | sibling branches (which *share* a merge-base) and amend/rebase orphans |

Without the ancestry check a checkpoint from a sibling branch passes validation, and `git diff <its-head>` renders that branch's commits as reversals — a span the user never made.

**Accepted limitation:** the checkpoint is a commit SHA, and `hunk diff <sha>` includes the working tree, so uncommitted work already reviewed under a base `/diff` reappears in the next `/diff last`. Recording a dirty-tree snapshot (`git stash create`) would close it at the cost of dangling objects and GC coupling; the clean-tree assumption is the deliberate trade.

`herdr pane split` has no `--label` flag, so the pane's terminal title comes from hunk rather than carrying the mode. Two concurrent reviews of the same worktree are not supported — only one review per worktree runs at a time, tracked by `OwnedReview`.

## Flow

```
herdr pane split $HERDR_PANE_ID --direction right --ratio 0.5 --cwd <worktree> \
                --no-focus --env HUNK_DISABLE_UPDATE_NOTICE=1
herdr pane run <pane_id> 'hunk' 'diff' '<target>' ['--agent-context' '<sidecar>']
hunk session comment list --repo <worktree> --type user --json
herdr pane close <pane_id>
```

The default target is `merge-base(detectDefaultBranch(), HEAD)` passed as a **single** argument. `hunk diff <target>` becomes `git diff --no-ext-diff --find-renames <target>`, so one view carries committed *and* uncommitted work — three-dot `main...HEAD` would show only commits. On the default branch the merge-base is HEAD, which degrades to a working-tree diff with no special case. `/diff last` substitutes the recorded checkpoint SHA as the target; nothing else in the flow changes.

All behaviour recorded here was verified against hunk 0.17.6 and herdr 0.7.5. hunk is pre-1.0 and host-installed, so these are observations of a moving target, not a contract.

## Why the session blocks

hunk keeps notes **in memory only**. Its on-disk state holds just the update notice and extension trust; sessions register over a socket and deregister when the window closes. Notes die with the window.

So the read has to happen while the session is alive, and the pi-side confirm is what guarantees the ordering: blocking pi makes returning to pi the natural path rather than quitting hunk. This is a mitigation, not a guarantee — quitting hunk first still loses that review's notes, and nothing on our side can intercept it.

Notes are read on cancel as well as confirm. Text the user already wrote is theirs, not a draft.

## Annotation lifecycle

The agent annotates **as it works**, not once at the end. Each `annotate_changeset` call merges into the per-worktree sidecar (same-path entries coalesce, exact duplicates collapse by key, a corrected rationale supersedes in place, latest summaries win), and the next review of the same span renders everything accumulated. At review close — notes read, pane closed — the sidecar is **cleared**, but only when that review actually attached it: clearing rationale a launch never rendered would destroy it unread, so an unattached sidecar is left for the review that can show it. On any earlier failure (unread notes, unopened pane) nothing is consumed, so a retry sees the same span with its rationale intact.

The anchor is **span identity, not a diff target**. Annotations are stamped with the review base, and a launch attaches the sidecar when that base still matches — in either mode. This works because annotation ranges are recorded against the *new* side of the diff, which is the working tree whichever target is used: rationale valid for an incremental view is equally valid in the full one. Matching against the launch target instead is the trap — the annotate-time anchor and a `/diff last` target are different quantities, so on a feature branch they never agree and a full `/diff` silently renders nothing. Stamping the base also makes the anchor stable as commits land, which is what lets calls accumulate rather than replace each other; a call carrying a genuinely different base replaces the files, because that rationale describes a span that is gone.

Each annotation carries a deterministic key (`sha256(path, range, summary, rationale)[:12]`), returned in the tool confirmation — which reports what *this call* added, so the count and the listed keys describe the same set. `remove_annotation(key)` withdraws one — the case it exists for is annotate → revise the code above it → withdraw the mis-anchored note → annotate again. Removal prunes empty file entries and deletes an emptied sidecar outright (hunk is never handed a husk). An unknown key errors loudly — it usually means a completed `/diff` already consumed it.

The rationale reaches the user only through the sidecar, and the user's notes reach the agent as a **user message** — they are the user's own words, so they arrive as if typed rather than as extension output. Only annotations the user actually wrote are delivered; an empty review notifies and sends nothing.

## Why sidecars are launch-only

Agent annotations travel as hunk's `--agent-context` JSON sidecar rather than its live `comment apply` API, because `comment apply` needs a pane that does not exist when an agent finishes work, and anchors to a single `line` where the sidecar carries a `newRange`. "Annotate as you work" therefore means annotations *accumulate on disk*; they render at the next `/diff`, never in a live session.

Sidecars are only ever passed at **launch**:

| | out-of-root sidecar path |
|---|---|
| launch | accepted |
| `hunk session reload` | refused — `Session reload refused agent context path outside the initial Hunk root` |

Putting the sidecar inside the root would satisfy reload, but not in a worktree: there `.git` is a *file* and the real gitdir lives under the main checkout, outside the worktree root, while anything in the working tree itself shows up as an untracked file in the diff being reviewed. Worktrees are Basecamp's normal mode, so `/diff` never reloads — each invocation launches a fresh session, which also sidesteps the note-wipe below.

## Reload discards notes across scopes

Reloading a session to the **same** ref preserves its notes; reloading to a **different** ref destroys all of them, agent notes included, with no warning. `/diff` therefore replaces sessions rather than repointing them, and drains a leftover session's user notes before closing its pane.

The pane id is `processScoped` (`basecamp.diffPanes`) because a hunk pane outlives the session that opened it; losing the id on `/reload` would strand a pane nothing can close.

## `herdr pane run` is unescaped send-keys

`pane run` types its argument list into the target pane's shell and escapes nothing — `$HOME` expands and `a;touch x` executes. It also cannot re-launch into a pane already running a TUI; keystrokes go to the TUI instead, so closing is `herdr pane close`, never a sent `q`.

`runInHerdrPane` single-quotes every element, including the command name. Git refs legally contain `;`, `$`, `&`, and backticks, so this is a correctness requirement rather than hardening. `/diff` accepts a **closed keyword set** — nothing, or `last` — parsed into a mode enum before anything runs; anything else errors without touching the shell. The invariant that no user input reaches the shell is unchanged: the SHAs that reach the argv are resolved by Basecamp from git, never parsed from the argument string.

`herdr pane split` splits the current session's pane (`$HERDR_PANE_ID`) rightward, so the diff appears side-by-side in the same tab rather than in a separate tab. `pane split` has no `--label` flag, so the pane's terminal title comes from hunk rather than being set to "diff: <label>".

## Annotation staleness

Ranges are recorded against the new side of the diff at call time and are not re-anchored afterwards, so editing an annotated file above an annotated range silently mis-anchors it. Mid-work annotation makes this a real risk rather than a once-per-task one; `remove_annotation` + re-annotate is the mitigation, and the tool description tells the agent so.

hunk itself fails two ways on stale input, neither loudly: an annotation on a file absent from the changeset is **silently dropped**, and a range past EOF is kept but mis-anchored. The durable fix is anchor-text re-location at sidecar-generation time; that is deliberately not built yet.

## Boundaries

Code review is untouched. `report_findings` and the `pi/code-review/annotate/` pane still own review findings; whether hunk should also render them is an open question, not an oversight.
