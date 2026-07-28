# diff

Basecamp's diff/review surface, filling the gap left when Companion was retired: `/diff` opens [hunk](https://github.com/modem-dev/hunk) in a Herdr tab, blocks the session while you review, and returns your inline annotations as line-anchored feedback. `annotate_changeset` lets the working agent put its own rationale beside the same diff.

Basecamp launches and drives hunk; hunk renders and captures. Both are hard dependencies — absent Herdr or hunk, `/diff` reports why and changes nothing.

## Checkpoints: `/diff` vs `/diff last`

Reviews are user-initiated checkpoints. Each completed `/diff` records the worktree's HEAD SHA, and `/diff last` shows only what moved since that point:

```
/diff        → full review vs merge-base; checkpoint := HEAD
…commits land…
/diff last   → what changed since that checkpoint
/diff        → full review; checkpoint moves up
```

`/diff last` never advances the checkpoint — it is a second look at the same span, so running it twice shows the same incremental diff. With no recorded checkpoint it falls back to a full review (with a notice) and records one. Empty diffs run normally and still record.

Checkpoints live in a `processScoped` map (`basecamp.diffCheckpoints`) keyed by worktree: they survive `/reload` but not a restart — deliberately, since hunk sessions die with the process too. Each checkpoint also records the merge-base it was taken against, and is dropped when that base no longer resolves: worktree directories are reused across branches, and a checkpoint taken on one branch is meaningless on another. Under the clean-tree assumption the checkpoint is just a SHA; nothing snapshots dirty-tree state.

The tab label carries the mode (`diff: <label> (last)`) so two tabs are distinguishable.

## Flow

```
herdr tab create --workspace $HERDR_WORKSPACE_ID --cwd <worktree> \
                 --label "diff: <label>" --no-focus --env HUNK_DISABLE_UPDATE_NOTICE=1
herdr pane run <pane_id> 'hunk' 'diff' '<target>' ['--agent-context' '<sidecar>']
hunk session comment list --repo <worktree> --type user --json
herdr tab close <tab_id>
```

The default target is `merge-base(detectDefaultBranch(), HEAD)` passed as a **single** argument. `hunk diff <target>` becomes `git diff --no-ext-diff --find-renames <target>`, so one view carries committed *and* uncommitted work — three-dot `main...HEAD` would show only commits. On the default branch the merge-base is HEAD, which degrades to a working-tree diff with no special case. `/diff last` substitutes the recorded checkpoint SHA as the target; nothing else in the flow changes.

All behaviour recorded here was verified against hunk 0.17.6 and herdr 0.7.5. hunk is pre-1.0 and host-installed, so these are observations of a moving target, not a contract.

## Why the session blocks

hunk keeps notes **in memory only**. Its on-disk state holds just the update notice and extension trust; sessions register over a socket and deregister when the window closes. Notes die with the window.

So the read has to happen while the session is alive, and the pi-side confirm is what guarantees the ordering: blocking pi makes returning to pi the natural path rather than quitting hunk. This is a mitigation, not a guarantee — quitting hunk first still loses that review's notes, and nothing on our side can intercept it.

Notes are read on cancel as well as confirm. Text the user already wrote is theirs, not a draft.

## Annotation lifecycle

The agent annotates **as it works**, not once at the end. Each `annotate_changeset` call merges into the per-worktree sidecar (same-path files append, exact duplicates collapse by key, latest summaries win), and the next `/diff` whose target matches the sidecar's stamp renders everything accumulated. At review close — notes read, tab closed — the sidecar is **cleared** and the checkpoint advances, in that order: the advance is what guarantees cleared rationale is never re-rendered against the same span. On any earlier failure (unread notes, unopened tab) neither happens, so a retry sees the same span with its rationale intact.

Annotations are stamped with the **last checkpoint** — the coordinates the next `/diff last` reviews — so rationale and review share line numbers by construction. With no checkpoint recorded the stamp falls back to HEAD, which under the clean-tree assumption *is* the last diff point; the store self-initializes. A merge only happens within one anchor: a call stamped with a different base replaces the sidecar's files, because anything carrying an older anchor was never reviewed and describes a span that is gone.

Each annotation carries a deterministic key (`sha256(path, range, summary)[:12]`), returned in the tool confirmation so the agent can reference it. `remove_annotation(key)` withdraws one — the case it exists for is annotate → revise the code above it → withdraw the mis-anchored note → annotate again. Removal prunes empty file entries and deletes an emptied sidecar outright (hunk is never handed a husk). An unknown key errors loudly — it usually means a completed `/diff` already consumed it.

## Why sidecars are launch-only

Agent annotations travel as hunk's `--agent-context` JSON sidecar rather than its live `comment apply` API, because `comment apply` needs a pane that does not exist when an agent finishes work, and anchors to a single `line` where the sidecar carries a `newRange`. "Annotate as you work" therefore means annotations *accumulate on disk*; they render at the next `/diff`, never in a live session.

Sidecars are only ever passed at **launch**:

| | out-of-root sidecar path |
|---|---|
| launch | accepted |
| `hunk session reload` | refused — `Session reload refused agent context path outside the initial Hunk root` |

Putting the sidecar inside the root would satisfy reload, but not in a worktree: there `.git` is a *file* and the real gitdir lives under the main checkout, outside the worktree root, while anything in the working tree itself shows up as an untracked file in the diff being reviewed. Worktrees are Basecamp's normal mode, so `/diff` never reloads — each invocation launches a fresh session, which also sidesteps the note-wipe below.

## Reload discards notes across scopes

Reloading a session to the **same** ref preserves its notes; reloading to a **different** ref destroys all of them, agent notes included, with no warning. `/diff` therefore replaces sessions rather than repointing them, and drains a leftover session's user notes before closing its tab.

The tab id is `processScoped` (`basecamp.diffTabs`) because a hunk tab outlives the session that opened it; losing the id on `/reload` would strand a tab nothing can close.

## `herdr pane run` is unescaped send-keys

`pane run` types its argument list into the target pane's shell and escapes nothing — `$HOME` expands and `a;touch x` executes. It also cannot re-launch into a pane already running a TUI; keystrokes go to the TUI instead, so closing is `herdr tab close`, never a sent `q`.

`runInHerdrPane` single-quotes every element, including the command name. Git refs legally contain `;`, `$`, `&`, and backticks, so this is a correctness requirement rather than hardening. `/diff` accepts a **closed keyword set** — nothing, or `last` — parsed into a mode enum before anything runs; anything else errors without touching the shell. The invariant that no user input reaches the shell is unchanged: the SHAs that reach the argv are resolved by Basecamp from git, never parsed from the argument string.

`herdr tab create` without an explicit `--workspace` creates the tab in whichever workspace currently has focus rather than the caller's, so `--workspace` is always sent.

## Annotation staleness

Ranges are recorded against the new side of the diff at call time and are not re-anchored afterwards, so editing an annotated file above an annotated range silently mis-anchors it. Mid-work annotation makes this a real risk rather than a once-per-task one; `remove_annotation` + re-annotate is the mitigation, and the tool description tells the agent so.

hunk itself fails two ways on stale input, neither loudly: an annotation on a file absent from the changeset is **silently dropped**, and a range past EOF is kept but mis-anchored. The durable fix is anchor-text re-location at sidecar-generation time; that is deliberately not built yet.

## Boundaries

Code review is untouched. `report_findings` and the `pi/code-review/annotate/` pane still own review findings; whether hunk should also render them is an open question, not an oversight.
