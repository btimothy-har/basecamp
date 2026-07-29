# bash-reviewer

Basecamp bash reviewer — LLM gate for risky git/gh/shell commands.

## What it does

- **Bash reviewer hook**: registers a `tool_call` hook for `bash`
- **Reviewer runtime**: hosts the LLM gate for risky git/gh/shell commands
- **Multi-line triage**: a single quote-aware scanner splits commands on shell separators — newlines, `&&`, `||`, `;`, `|`, `|&`, and a lone `&` (background) — so every command in a compound is classified rather than only the first. Because the scanner owns the separators, quoting protects them: `X='a;b' rm -rf /z` stays one segment and the classifier still sees `rm`. Redirection ampersands (`2>&1`, `&>`, `>&`) never split. Separators inside quotes, `$'…'`, comments, heredoc bodies, and backslash line continuations are data. Heredocs are recognized only outside parentheses, so arithmetic shifts (`$((1 << n))`) cannot swallow the rest of the command as data; an unterminated heredoc is rescanned as code rather than dropped. A heredoc body fed to a shell interpreter (`bash <<EOF`) is recursively triaged; other openers (`cat <<EOF`) keep the body as data. Redirections written before the command word (`<<EOF bash`, `2>/dev/null git push`) are skipped when locating the executable, so they cannot hide it from classification.
- **Known gaps**: compound one-liners (`for f in *; do rm -rf $f; done`), `eval`, `timeout` wrappers, and nested `$(...)` command substitutions remain unclassified and fall through to `allow`.
- **Wide-search block**: recursive filesystem searches (`grep -r`, `find`, `rg`, `ag`, `ack`, `fd`) rooted at a system or home root (`/`, `~`, `$HOME`, `/usr`, `/etc`, `/Users`, …) are blocked deterministically during triage, before the LLM gate — whole-system scans are slow. Targeted searches (relative roots, subpaths, non-recursive single-file grep) are unaffected.

## Opting out

The reviewer is skipped only when **three** signals agree: `BASECAMP_BASH_REVIEWER=off`, `BASECAMP_EXTERNAL_SANDBOX=1`, and the `--unsafe-edit-sandboxed` launch flag — the same flag the sandboxed-edit gate in `#core/project/workspace/session.ts` pairs with the sandbox env var. The two env vars are one channel (`process.env`, which a repo `.env` or a stray export can populate), so env alone must never strip the gate; the flag rides on argv, which a `.env` cannot forge. Daemon-spawned agents never see the env pair at all — the spawn env strips both — and `loadDotenv` refuses every `BASECAMP_` key.

The check runs **per call**, and the `tool_call` hook is always registered: an opted-out session still carries the reviewer, and `/reload` cannot silently change whether the gate exists.

The Terminal-Bench eval profile is the only caller; it passes the flag on the pi command line alongside the env vars. There the trial container never receives basecamp's `config.json`, so the reviewer's `fast` alias cannot resolve; every gate verdict would fall through to the no-UI failsafe and hard-block a command the shipped reviewer would have judged on its merits. Scoring that measures a missing alias rather than the agent. Each trial's `basecamp-eval.json` records `bash_reviewer_enabled: false` so no score is read as if the gate were present.

## Autonomous subagents

Subagent context is detected with `BASECAMP_AGENT_DEPTH > 0`. In a subagent, `route_to_user` decisions collapse to approve only for `git-mutation` commands, which are sandbox-local and reversible. Other categories, including gh publish operations, irreversible remote mutations, and dangerous shell commands, are denied. Interactive sessions still prompt the user, and failsafe paths remain fail-closed.

## Dependencies

- **core** (`#core/*`): shared Basecamp/Pi runtime primitives
- **@earendil-works/pi-ai**: model API used by the reviewer
