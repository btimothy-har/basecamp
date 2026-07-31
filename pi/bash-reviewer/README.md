# bash-reviewer

Basecamp bash reviewer — the `tool_call` hook that decides whether a `bash` command runs.

## What it does

- **Bash reviewer hook**: registers a `tool_call` hook for `bash`
- **Fast path**: `isTriviallySafe` recognizes a narrow class of read-only commands and lets them run with no model call
- **LLM gate**: everything else is judged by `RULESET` in `llm.ts` against the `fast` model alias, returning `approve` / `route_to_user` / `deny` with a risk level and a category

## The governing invariant

**A static check may only restrict, never grant permission.**

The reviewer used to open with a 1230-line hand-rolled bash parser: it split a command into segments, classified each one, and returned `allow`, a deterministic `block`, or a `gate`. An `allow` short-circuited the whole reviewer — the command ran with no model consulted. That made the parser a permission-granting oracle, so every gap in it was a bypass.

One review cycle found three. `$(( 1 << n ))` was misread as a heredoc opener that swallowed the following lines as data. `X='a;b' rm -rf /z` hid the executable behind a quote-blind split. `rm>file` fused into a single token that matched no command name. Three different bugs, one cause.

**A better parser would not have fixed this.** `for f in *; do rm -rf $f; done`, `eval "rm -rf /x"`, `timeout 5 rm -rf /x`, `(rm -rf /x)` and `diff <(rm -rf /x) f` all returned `allow` with the splitter working perfectly — classification gaps, not tokenizer gaps, and the list of shell constructs still needing a classifier has no end. So the verdict was inverted rather than the parser repaired: from *allow unless it looks dangerous* to *allow only if it is recognized*. An unrecognized construct gates instead of passing, and the parser is gone.

## Flow

`review.ts`, in order:

1. empty command → nothing to review
2. reviewer opt-out → skip entirely
3. `isTriviallySafe(command)` → run it, no model call
4. LLM gate → `approve` / `route_to_user` / `deny`

There is no triage phase and no deterministic block phase.

## The fast path

`isTriviallySafe(command: string): boolean` in `fast-path.ts` is the only permission-granting code in the reviewer. It is true only when **both** hold:

- every character is in `[A-Za-z0-9 \t\-_./,:@+]`;
- the first whitespace-delimited word is on a read-only allowlist (`ls`, `pwd`, `cat`, `head`, `tail`, `wc`, `stat`, `file`, `which`), or is `git` with a read-only subcommand as word two **and** no unrecognized option.

The executable allowlist admits only commands with no file-writing flag at all: `date` is absent because `date -s` sets the system clock, and `git bugreport`, `git diagnose` and `git fsck --lost-found` are absent because they create files despite reading like queries.

Git needs the extra option check because one option surface is shared across its read-only plumbing. `--output <file>` turns `git log`, `git show` and every `diff-*` subcommand into an arbitrary-file writer, and it needs no `=`, so nothing in the character test catches it; `git grep -O<pager>` launches a program. Enumerating the dangerous options would be the same losing game as parsing the shell, so the options are allowlisted instead — `--oneline`, `--stat`, `--porcelain`, `-5` and a dozen similar — and an unrecognized option gates. Being incomplete costs a round trip, never a bypass.

The character test is what removes the need for a parser. Everything a shell could use to hide a second command — `|`, `&`, `;`, `<`, `>`, `(`, `)`, `{`, `}`, `$`, backtick, backslash, quotes, glob characters, `!`, `~`, `#`, `=`, and newline — is outside the set, so a string that passes is provably one simple command of literal words: no expansion, substitution, redirection, separator, glob, or quote can hide in it. The allowlist then decides what that one command is allowed to be.

Search tools (`grep`, `rg`, `find`, `fd`, `ag`, `ack`) are deliberately **not** allowlisted — search scope is a judgment call and the model keeps making it. Interpreters and build tools (`npm`, `node`, `python`, `uv`, `make`) are not allowlisted because they run arbitrary code.

## The gate

Everything else reaches the model, which returns a `category` alongside its decision: `git-mutation`, `gh-publish`, `irreversible-remote`, `destructive-local`, `bq-query`, `wide-search`, or `other`. Downstream handling keys off it.

The `RULESET` is **grouped by outcome** — deny rules (D1–D5), route_to_user rules (U1–U5), approve rules (A1–A3) — under one precedence meta-rule: when several rules match, the most restrictive outcome wins. That single line replaces the per-rule cross-references a flat rule list needed ("defer to R5", "R2 already covers this"), which is what kept earlier revisions from staying self-consistent.

The gate's spatial concept is **cwd containment**, not worktree semantics. The input carries the directory the command runs from (the workspace effective cwd); file mutations targeting paths inside cwd or the system temp dir are approved as normal development work (A2), while mutations outside both route to the user as destructive (U4). The risk definitions reference the same boundary. The model is told nothing about worktrees versus the protected checkout — a deliberate trade: in a bare no-worktree session cwd *is* the protected checkout, and contained bash edits there approve as risk `local`. For bash this gate is the only mechanism — the workspace guard blocks structured `edit`/`write` in the checkout but never blocks bash — so this is a policy choice, not a coverage assumption: a checkout edit is a git-tracked, easily reverted change, squarely risk `local`, and hygiene steering (keep the checkout clean, earn a worktree) belongs to the agent prompt and the structured-write block, not to a blast-radius gate. Bash-side hygiene enforcement, if ever wanted, belongs in the workspace guard — which already rewrites the bash cwd when a worktree is active — not in this prompt.

Three policies that used to be deterministic pre-LLM blocks are gate deny rules: raw `bq query` through bash (D3), recursive searches rooted at a system or home directory (D4), and mutating `git worktree` subcommands — add, move, remove, lock, unlock, prune (D2). `git worktree list` is read-only and approved, and D2 matches only the `git worktree` subcommand itself, never other commands that merely run inside a worktree directory. The first two are scope judgments the model makes better than a regex — the old wide-search check needed tokenization just to tell `grep -r foo /` from `grep -r foo ./src`.

**Fail-closed defence in depth survives without a parser.** A gate `approve` carrying `risk === "destructive"` is upgraded to `route_to_user`, so a single model slip toward approve still cannot silently force-push; the self-contradiction is caught by the reviewer rather than by the shell.

**There is no intent-alignment rule.** Recent human messages gate destruction only: U3 requires explicit authorization for destructive-local commands and D5 denies unrequested destruction. The catch-all (U5) keys on the command itself being unusual for routine development — piping a downloaded script into a shell, driving an unfamiliar service — never on whether a routine command traces back to the conversation. Normal git operations (A1, including a plain push to a feature branch) and contained file edits (A2) are approve rules, not judgment calls, so the gate cannot second-guess reversible development work.

## Autonomous subagents

Subagent context is detected with `BASECAMP_AGENT_DEPTH > 0`. In a subagent, `route_to_user` collapses to approve only when the category is `git-mutation` — sandbox-local and reversible. Every other category, including gh publish operations, irreversible remote mutations, and destructive local commands, is denied. Interactive sessions still prompt the user.

## Failsafe

No resolvable model, no verdict returned, or any thrown error means prompt when there is an interactive UI and deny when there is not.

Its blast radius is smaller than a pure gate-everything design would give: the fast path consults no model, so a missing `fast` alias no longer leaves a headless session unable to run any bash at all.

## The recognizer is a seam

`isTriviallySafe` has a single signature so its body can be swapped without touching the flow. The deferred option is an `sh-syntax` (WASM wrapper around mvdan/sh) AST recognizer — gate on parse error, allow only when every node is a recognized type, there is no redirection or substitution, and every executable is on the same allowlist. Same invariant, wider recognizer; it would buy `ls -la | head` and `cat a && cat b`.

Deferred, not rejected. It adds a WASM dependency to the security control itself, in an extension whose entire runtime dependency set is three packages (`@playwright/cli`, `@sinclair/typebox`, `ws`), and the real-world gain is limited: read-only pipelines usually involve `grep`/`rg`, which gate anyway, and this harness gives the agent dedicated read and search tools instead of bash. **Adoption trigger**: every gate decision already writes an audit entry containing the command, so audit-log evidence of a high volume of gated-but-obviously-safe commands is what justifies paying that cost.

## Opting out

The reviewer is skipped only when **three** signals agree: `BASECAMP_BASH_REVIEWER=off`, `BASECAMP_EXTERNAL_SANDBOX=1`, and the `--unsafe-edit-sandboxed` launch flag — the same flag the sandboxed-edit gate in `#core/project/workspace/session.ts` pairs with the sandbox env var. The two env vars are one channel (`process.env`, which a repo `.env` or a stray export can populate), so env alone must never strip the gate; the flag rides on argv, which a `.env` cannot forge. Daemon-spawned agents inherit the trio only as a whole: `#core/swarm`'s spawn env strips the pair unless the dispatching parent's **own argv** carries `--unsafe-edit-sandboxed` (`isExternalSandboxLaunch` in `pi/core/swarm/agents/executor.ts`), in which case the pair and the flag propagate to the child together — an externally sandboxed process tree stays sandboxed, while an env-only chain can never assemble the disable state. `loadDotenv` refuses every `BASECAMP_` key.

The check runs **per call**, and the `tool_call` hook is always registered: an opted-out session still carries the reviewer, and `/reload` cannot silently change whether the gate exists.

The Terminal-Bench eval profile is the only caller; it passes the flag on the pi command line alongside the env vars. There the trial container never receives basecamp's `config.json`, so the reviewer's `fast` alias cannot resolve; every gate verdict would fall through to the no-UI failsafe and hard-block a command the shipped reviewer would have judged on its merits. Scoring that measures a missing alias rather than the agent. Each trial's `basecamp-eval.json` records `bash_reviewer_enabled: false` so no score is read as if the gate were present.

## Temporary escape hatch

`/bash-guard` is a session-level toggle that skips the LLM gate without touching the durable opt-out triad. `/bash-guard off` pauses the gate; `/bash-guard on` resumes it; with no argument it toggles. The fast path (`isTriviallySafe`) still runs regardless — only the model gate is skipped.

The pause is backed by `BASECAMP_BASH_REVIEWER_PAUSED` on `process.env`, so it propagates to subagent spawns (`buildAgentEnv` copies every `BASECAMP_*` var; this one is not in `RESTRICTED_AGENT_SPAWN_ENV_VARS`). It survives `/reload` but not a process restart, and `loadDotenv` refuses it from a repo `.env`. The status — `🛡 on` or `🛡 off` — is published through `ctx.ui.setStatus` and appears in the footer's third line alongside other extension statuses.

It is **not a security control**: the env+flag triad above remains the only durable opt-out, and a subagent that turns its own gate off affects only its own process.

## Dependencies

- **core** (`#core/*`): shared Basecamp/Pi runtime primitives
- **@earendil-works/pi-ai**: model API used by the reviewer
