# code-review

A standalone feature domain: the user-invoked `code-review` **skill** plus the `report_findings`
tool. It runs an independent, third-party review of the current branch — the top-level session
orchestrates the reviewers and relays their findings as the reviewee, but never authors the findings
or decides the verdict. Invoke it with `/skill:code-review [base]`; it is hidden from the model
(`disable-model-invocation`, so not agent-invocable) and never exposed in subagents.

## Flow

The `code-review` skill (`skills/code-review/SKILL.md`) drives the top-level session:

1. Load the `agents` skill — the swarm dispatch/wait tools require it.
2. Resolve scope: the current branch vs its base (`origin/HEAD`, falling back to `main`; an argument
   overrides the base) and the merge-base — covering committed, staged, unstaged, and untracked work.
3. `dispatch_agent` the six fixed reviewer specialists (`security-specialist`, `testing-specialist`,
   `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`),
   read-only, each with a self-contained scope-only brief. Reviewers self-resolve the diff — no
   author narration.
4. `dispatch_agent` additional `general-reviewer`s for any material aspect the fixed six don't cover
   (migration, concurrency, performance, public API/contract, build/CI).
5. `wait_for_agent` on all handles; read each reviewer's plain-text report inline.
6. Call `report_findings({ scope, findings })`, carrying every finding through verbatim (severity
   included), with an optional per-finding `response` — never dropping or softening one.

`report_findings` (`tools.ts`) is the only tool. It merges the findings, computes the verdict
deterministically (any critical → Request Changes; ≥3 high → Request Changes; 1–2 high → Comment;
only medium/low → Approve with notes; none → Approve — the verdict ignores `response`), opens the
interactive annotate pane (finding → author `response` → user reaction) when a UI is available,
persists a private JSON packet to scratch (structured findings + responses + reactions; raw reviewer
prose is not retained), and returns the verdict framing to the reviewee.

## Layout

- `index.ts` (`registerCodeReview`) — registers `report_findings` and exposes the skill primary-only
  via a `resources_discover` hook.
- `skills/code-review/SKILL.md` — the orchestration skill (`disable-model-invocation`, user-invoked).
- `tools.ts` — the `report_findings` tool.
- `findings.ts` — the `Finding` / `Dimension` / `Severity` / `ReviewScope` schemas + `ReportFindingsParams`.
- `synthesis.ts` — `mergeFindings` + `computeVerdict`.
- `annotate-pane.ts` — the interactive reaction/response pane.
- `artifact.ts` — the `ReviewResult` record + packet persistence.

The domain owns no dispatch orchestration — the skill drives the reviewers through the swarm tools —
and its only cross-domain import is `#core/host/env` (`isSubagent`). It is manual only. v1 reviews
the current branch; PR and arbitrary-branch targets are a planned follow-up.
