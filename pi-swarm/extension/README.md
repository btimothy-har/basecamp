# pi-swarm extension package

This package owns the TypeScript runtime for Basecamp async-agent features: public daemon tools, launch policy, daemon client/reporting code, and dependency-injected registration helpers.

`registerPiSwarm(pi, deps)` hosts the async-only surface for this domain: the agent catalog provider plus daemon client, tools, and reporting.

## Code review

`/code-review` runs an independent, third-party review of the current branch. The command owns orchestration end-to-end — the primary agent triggers it and receives the result, but never authors or synthesizes it.

Flow:

1. Resolve scope: the current branch vs its base (`origin/HEAD`, falling back to `main`; an optional argument overrides the base).
2. Dispatch six independent reviewer agents (`security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`) via the daemon client with a fixed, scope-only brief — they read the diff directly, with no author narration.
3. Transpose each reviewer's prose report into a canonical `Finding` schema with a per-report LLM pass (the `fast` model, a forced `report_findings` tool) — faithful extraction only, no cross-report consolidation.
4. Merge findings and compute a verdict with deterministic code (no LLM synthesis): any critical → Request Changes; ≥3 high → Request Changes; 1–2 high → Comment; only medium/low → Approve with notes; none → Approve.
5. Persist the full report (including each reviewer's raw prose) to scratch and inject a framing prompt so the primary agent triages the findings as the reviewee.

The review module lives in `src/agents/review/` (`findings`, `transpose`, `synthesis`, `orchestrate`, `format`, `command`). It is manual only — there is no automatic or backgrounded firing. v1 reviews the current branch; PR and arbitrary-branch targets are a planned follow-up.

