---
name: code-review
description: Independent multi-agent review of the current branch. Dispatches the fixed reviewer specialists plus adaptive general reviewers over the branch diff, then reports structured findings to an annotation pane for the user. Runs only in the top-level session; invoke with /skill:code-review [base].
disable-model-invocation: true
---

# Code review

Run an independent review of the current branch. **You are the reviewee** — you orchestrate the
reviewers and relay their findings, but you do not author findings or decide the verdict. The
reviewers are independent specialists; their briefs are context for them, never instructions you use
to narrow or soften what they report.

Run these steps in order.

## 1. Load the agents skill

The dispatch/wait tools below require it. Invoke `skill({ name: "agents" })` first, before any
`dispatch_agent` call.

## 2. Resolve the review scope

Using bash:

- `base` — the argument passed to `/skill:code-review`, if given; otherwise
  `git symbolic-ref --quiet --short refs/remotes/origin/HEAD` (fall back to `main`).
- `mergeBase` — `git merge-base <base> HEAD`.
- If `git diff --quiet <mergeBase>` reports no tracked changes **and**
  `git ls-files --others --exclude-standard` is empty, there is nothing to review — stop and say so.

Keep `base`, `mergeBase`, the current branch (`git branch --show-current`), and the repo working
directory (`cwd`) — you pass them to `report_findings` as `scope` (`label` reads like
`branch <current> → <base>`).

## 3. Dispatch the fixed reviewers

`dispatch_agent` all six in parallel, each read-only. Give every reviewer the same self-contained
brief (they get no conversation history, so it must stand alone):

> Review the code changes on this branch (base `<base>`) in `<cwd>`, including any uncommitted work.
> Run git yourself: `git diff <mergeBase>` shows every committed and uncommitted change since the
> branch diverged; also run `git status --short` for untracked files and read the changed and added
> files directly. Assess only what your specialist role covers. Report findings only — do not modify
> files or write fixes.

The six agents and the `dimension` their findings map to:

| agent | dimension |
|-------|-----------|
| `security-specialist` | `security` |
| `testing-specialist` | `testing` |
| `docs-specialist` | `docs` |
| `code-clarity-specialist` | `clarity` |
| `conventions-specialist` | `conventions` |
| `general-reviewer` | `general` |

Collect the six `agent_handle`s.

## 4. Dispatch adaptive reviewers

Skim `git diff --stat <mergeBase>`. For any material aspect the fixed six do not own — a database
migration, a concurrency/ordering change, a performance-sensitive path, a public API/contract
change, build/CI wiring — `dispatch_agent` an extra `general-reviewer` with the same brief plus an
explicit aspect focus. Do not duplicate a fixed lens. Add their handles to the list.

## 5. Wait for the reviewers

Call `wait_for_agent({ handles: [<all handles>], timeout_s: 600 })` once. Each result carries the
reviewer's plain-text report inline. If a reviewer failed or returned nothing, note it — do not
fabricate findings on its behalf.

## 6. Report the findings

Call `report_findings({ scope, findings })`:

- **Carry every finding from every reviewer, verbatim.** Transpose each into the structured shape
  (`dimension`, `severity`, `file`, `lineStart`/`lineEnd`, `title`, `detail`, `remediation`), copying
  the reviewer's stated severity exactly. Set `dimension` from the producing reviewer; adaptive
  `general-reviewer` findings use `general`.
- You may add a per-finding `response` — your own opinion where you agree, disagree, or add context.
  **Never omit, merge away, or soften a finding to avoid it.** Disagreement belongs in `response`,
  not in a dropped finding. The verdict is computed from severities and ignores `response`.

`report_findings` computes the verdict, opens the annotation pane for the user, and writes the review
packet. You then receive the packet as the reviewee and discuss next steps with the user — you do not
start editing code on your own.
