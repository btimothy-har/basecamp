# pi-swarm extension package

This package owns the TypeScript runtime for Basecamp async-agent features: public daemon tools, launch policy, daemon client/reporting code, and dependency-injected registration helpers.

`registerPiSwarm(pi, deps)` hosts the async-only surface for this domain: the agent catalog provider plus daemon client, tools, and reporting.

## Code review

`/code-review` runs an independent, third-party review of the current branch. The command owns orchestration end-to-end — the primary agent triggers it and receives the result, but never authors or synthesizes it.

Flow:

1. Resolve scope in the active worktree: the current branch vs its base (`origin/HEAD`, falling back to `main`; an optional argument overrides the base). The review covers every change since the branch's merge-base with the base — committed, staged, unstaged, and untracked — so uncommitted work is included.
2. Dispatch six independent reviewer agents (`security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`) via the daemon client with a fixed, scope-only brief — they read the diff directly, with no author narration.
3. Transpose each reviewer's prose report into a canonical `Finding` schema with a per-report LLM pass (the `fast` model, a forced `report_findings` tool) — faithful extraction only, no cross-report consolidation.
4. Merge findings and compute a verdict with deterministic code (no LLM synthesis): any critical → Request Changes; ≥3 high → Request Changes; 1–2 high → Comment; only medium/low → Approve with notes; none → Approve. The review is fail-fast and all-or-nothing: if any reviewer fails to dispatch, complete, produce output, or transpose into structured findings, the entire review aborts with a notification naming the failing reviewer — no verdict and no partial result are produced.
5. When a UI is available, present an interactive per-finding reaction pane so the user can page through the findings and leave an optional free-text reaction on each before the agent engages (reactions seed the follow-up discussion; they are not accept/reject decisions).
6. Persist a JSON artifact to scratch — the structured findings plus the user's per-finding reactions; raw reviewer prose is not retained. Then inject a compact framing prompt carrying the verdict, counts, and a link to the artifact (the findings themselves are not dumped inline) so the primary agent reads the packet and triages as the reviewee.

The review module lives in `src/agents/review/` (`findings`, `transpose`, `synthesis`, `orchestrate`, `format`, `command`, `annotate-pane`, `command-helpers`). It is manual only — there is no automatic or backgrounded firing. v1 reviews the current branch; PR and arbitrary-branch targets are a planned follow-up.

## Agent lifecycle

Dispatched agents can be stopped with the `cancel_agent` tool, which cancels an agent you dispatched and terminates its process (subtree-only: you cannot cancel agents outside your dispatch tree). Agents are also reaped automatically when their dispatcher session ends and does not reconnect within `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default 3600s). See `pi-swarm/protocol/PROTOCOL.md`.

