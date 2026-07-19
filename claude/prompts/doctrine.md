# Engineering doctrine

Shared standards for all basecamp coding work — the main session and every dispatched subagent alike.

## Before you change anything

- **Read before modifying.** Never propose or make changes to a file you haven't read.
- Prefer editing existing files over creating new ones — including markdown.

## Code quality

Priorities, in order: **readability → established patterns → simplicity.**

- Clear naming and obvious intent over cleverness.
- Follow the conventions already in the file and the codebase.
- **Strong typing** on function signatures, data structures, and public interfaces. Types are documentation and safety, not overhead.
- **Security awareness.** Don't introduce injection, XSS, or other OWASP-top-10 issues; fix insecure code you touch.
- **Apply the relevant engineering skill.** basecamp ships skills carrying the detailed, per-domain standards — `python-development` for Python, `sql` for queries and schema design, `data-warehousing` for dbt models, `data-analysis` for metrics and investigation, `marimo` for reactive notebooks. When your work is in one of these domains, follow its skill over improvising; this doctrine is the baseline, the skill has the specifics.

## Comments and docstrings

Comments are for context the code cannot express. If the code can say it, the code should say it.

- **Never comment the "what."** If a comment restates the name, the loop, or the condition, delete it.
- **No section dividers.** No `# === Section ===`, no `# --- Setup ---`. If a function needs internal sections, it's too long — extract functions.
- **Comment the "why," only when non-obvious:** a non-obvious approach, a workaround for a known bug/limitation (with a reference), load-bearing ordering, or an embedded business rule.
- **Docstrings are terse, not prose.** No "This function…" filler. Add parameter/return notes only when names and types don't already make it clear. Omit them on self-documenting private functions.

## Simplicity and focus

- Make only the change asked for or clearly necessary. A bug fix doesn't drag in surrounding cleanup; a simple feature doesn't grow extra configurability.
- No speculative error handling, fallbacks, or validation for cases that can't happen. Validate at system boundaries (user input, external APIs); trust internal code and framework guarantees.
- No helpers or abstractions for one-off operations. Three similar lines beat a premature abstraction.
- **Delete completely.** No backwards-compatibility shims, renamed `_unused` vars, re-exported types, or `// removed` comments. If something is unused, remove it.

## Testing

Context-dependent. Not every task needs tests — config, scripts, docs, and exploratory work usually don't. Match testing effort to what's actually at risk, not to a coverage target.

## Scratch space

A scratch directory is provisioned for you at `$BASECAMP_SCRATCH_DIR`. Use it for throwaway artifacts — scripts, query results, intermediate output. If the variable is unset, fall back to `/tmp/claude/<repo>` and create it yourself. It's disposable and never checked into git; don't keep anything there you need to survive the session.

## Git

- Commit at completed logical checkpoints, not reflexively. Skip commits for investigation, review-only, or non-mutative work.
- Run `git status` before staging. Stage only what belongs to the current task; don't sweep up unrelated or pre-existing changes. If you can't isolate cleanly, ask first.
- Don't push, force-push, delete refs, or open/merge PRs unless the task explicitly calls for it. Confirm with the user before any irreversible remote operation.

## Python

Python 3.12+ with the `uv` package manager. Run scripts with `uv run` (`uv run script.py`, or `uv run python -m module`); don't call `python` or `pip` directly. For standalone scripts, declare dependencies with PEP 723 inline metadata — `uv run` installs them into an isolated environment automatically:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pandas"]
# ///
```

## No time estimates

Never estimate how long work will take. Focus on what needs doing and let the user judge timing for themselves.
