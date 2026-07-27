# diff

Basecamp's diff/review surface, filling the gap left when Companion was retired: `/diff` opens [hunk](https://github.com/modem-dev/hunk) in a Herdr tab, blocks the session while you review, and returns your inline annotations as line-anchored feedback. `annotate_changeset` lets the working agent put its own rationale beside the same diff.

Basecamp launches and drives hunk; hunk renders and captures. Both are hard dependencies — absent Herdr or hunk, `/diff` reports why and changes nothing.

## Flow

```
herdr tab create --workspace $HERDR_WORKSPACE_ID --cwd <worktree> \
                 --label "diff: <label>" --no-focus --env HUNK_DISABLE_UPDATE_NOTICE=1
herdr pane run <pane_id> 'hunk' 'diff' '<base>' ['--agent-context' '<sidecar>']
hunk session comment list --repo <worktree> --type user --json
herdr tab close <tab_id>
```

Scope is `merge-base(detectDefaultBranch(), HEAD)` passed as a **single** target. `hunk diff <target>` becomes `git diff --no-ext-diff --find-renames <target>`, so one view carries committed *and* uncommitted work — three-dot `main...HEAD` would show only commits. On the default branch the merge-base is HEAD, which degrades to a working-tree diff with no special case.

All behaviour recorded here was verified against hunk 0.17.6 and herdr 0.7.5. hunk is pre-1.0 and host-installed, so these are observations of a moving target, not a contract.

## Why the session blocks

hunk keeps notes **in memory only**. Its on-disk state holds just the update notice and extension trust; sessions register over a socket and deregister when the window closes. Notes die with the window.

So the read has to happen while the session is alive, and the pi-side confirm is what guarantees the ordering: blocking pi makes returning to pi the natural path rather than quitting hunk. This is a mitigation, not a guarantee — quitting hunk first still loses that review's notes, and nothing on our side can intercept it.

Notes are read on cancel as well as confirm. Text the user already wrote is theirs, not a draft.

## Why sidecars are launch-only

Agent annotations travel as hunk's `--agent-context` JSON sidecar rather than its live `comment apply` API, because `comment apply` needs a pane that does not exist when an agent finishes work, and anchors to a single `line` where the sidecar carries a `newRange`.

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

`runInHerdrPane` single-quotes every element, including the command name. Git refs legally contain `;`, `$`, `&`, and backticks, so this is a correctness requirement rather than hardening. `/diff` takes no arguments, which keeps user input out of the shell entirely.

`herdr tab create` without an explicit `--workspace` creates the tab in whichever workspace currently has focus rather than the caller's, so `--workspace` is always sent.

## Sidecar lifetime

A sidecar is written per worktree and overwritten, never deleted, so it outlives the tool call that produced it. It records the review base it was anchored against and is attached only while that base still resolves — worktree directories are deliberately reused across branches, so an unstamped match would render one branch's rationale against another branch's line numbers.

## Annotation staleness

`annotate_changeset` is called **once, when work is complete**. Ranges are recorded against the new side of the diff at call time and are not re-anchored afterwards, so editing an annotated file above an annotated range silently mis-anchors it.

hunk itself fails two ways on stale input, neither loudly: an annotation on a file absent from the changeset is **silently dropped**, and a range past EOF is kept but mis-anchored. Making mid-work annotation safe needs anchor-text re-location at sidecar-generation time; that is deliberately not built yet.

## Boundaries

Code review is untouched. `report_findings` and the `pi/code-review/annotate/` pane still own review findings; whether hunk should also render them is an open question, not an oversight.
