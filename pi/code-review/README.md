# code-review

A standalone feature domain: the `/code-review` command, built on the agent-dispatch primitive (`#core/swarm`). It runs an independent, third-party review of the current branch — the primary agent triggers it and receives the result as the reviewee, but never authors or synthesizes it.

## Flow

1. Resolve scope in the active worktree: the current branch vs its base (`origin/HEAD`, falling back to `main`; an optional argument overrides the base). The review covers every change since the branch's merge-base with the base — committed, staged, unstaged, and untracked — so uncommitted work is included.
2. Dispatch six independent reviewer agents (`security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`) via the `#core/swarm` client with a fixed, scope-only brief — they read the diff directly, with no author narration.
3. Transpose each reviewer's prose report into a canonical `Finding` schema with a per-report LLM pass (the `fast` model, a forced `report_findings` tool) — faithful extraction only, no cross-report consolidation.
4. Merge findings and compute a verdict with deterministic code (no LLM synthesis): any critical → Request Changes; ≥3 high → Request Changes; 1–2 high → Comment; only medium/low → Approve with notes; none → Approve. The review is fail-fast and all-or-nothing: if any reviewer fails to dispatch, complete, produce output, or transpose into structured findings, the entire review aborts with a notification naming the failing reviewer — no verdict and no partial result are produced.
5. When a UI is available, present an interactive per-finding reaction pane so the user can page through the findings and leave an optional free-text reaction on each before the agent engages (reactions seed the follow-up discussion; they are not accept/reject decisions).
6. Persist a JSON artifact to scratch — the structured findings plus the user's per-finding reactions; raw reviewer prose is not retained. Then inject a compact framing prompt carrying the verdict, counts, and a link to the artifact (the findings themselves are not dumped inline) so the primary agent reads the packet and triages as the reviewee.

## Layout

The domain (`pi/code-review/`) is `index.ts` (`registerCodeReview`) plus the pipeline stages: `findings` (the `Finding`/`Dimension`/`report_findings` schemas), `transpose` (LLM prose → structured), `synthesis` (`mergeFindings`/`computeVerdict`), `orchestrate` (`runReview`, `REVIEWERS`), `format`, `command` (the orchestrator/entrypoint), `annotate-pane`, and `command-helpers`. It consumes the agent primitive (`createDaemonClient`, `buildAgentLaunchSpec`, `dispatchWithHandleRetry`, `discoverAgents`) from `#core/swarm/agents/*` and the extension root from `#core/host`.

It is manual only — there is no automatic or backgrounded firing. v1 reviews the current branch; PR and arbitrary-branch targets are a planned follow-up.
