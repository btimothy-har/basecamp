# bash-reviewer

Basecamp bash reviewer — LLM gate for risky git/gh/shell commands.

## What it does

- **Bash reviewer hook**: registers a `tool_call` hook for `bash`
- **Reviewer runtime**: hosts the LLM gate for risky git/gh/shell commands
- **Wide-search block**: recursive filesystem searches (`grep -r`, `find`, `rg`, `ag`, `ack`, `fd`) rooted at a system or home root (`/`, `~`, `$HOME`, `/usr`, `/etc`, `/Users`, …) are blocked deterministically during triage, before the LLM gate — whole-system scans are slow. Targeted searches (relative roots, subpaths, non-recursive single-file grep) are unaffected.

## Autonomous subagents

Subagent context is detected with `BASECAMP_AGENT_DEPTH > 0`. In a subagent, `route_to_user` decisions collapse to approve only for `git-mutation` commands, which are sandbox-local and reversible. Other categories, including gh publish operations, irreversible remote mutations, and dangerous shell commands, are denied. Interactive sessions still prompt the user, and failsafe paths remain fail-closed.

## Dependencies

- **core** (`#core/*`): shared Basecamp/Pi runtime primitives
- **@earendil-works/pi-ai**: model API used by the reviewer
