---
name: code-walkthrough
description: "Create a context-first code walkthrough review packet for a branch or PR, with architecture, decisions, diff evidence, validation, and targeted feedback."
---

# Code Walkthrough

Create a code-focused review packet for a branch or pull request, then call `review_packet`. The goal is to help the user review the actual code with enough context to understand why the changes matter.

Keep orientation brief. The walkthrough is for code review, not prose review: every substantive claim should be backed by visible code evidence. Use narrative to explain significance, make concrete changed code the review surface, and reserve raw diff evidence for `diff-evidence` cards.

## Context

Start from the context provided by the command or user message:

- Target label, such as `branch feature/foo` or `PR #123`
- `review_packet` target JSON
- Branch and base branch
- Optional PR metadata command
- User-provided review focus, if any

If target JSON is provided, use it as the `target` object when calling `review_packet`. If you determine the current head SHA, add it as `headSha`.

## Gather Evidence

Collect enough context to explain the target, then inspect the changed code directly:

```bash
git rev-parse HEAD
git log --oneline origin/$BASE..HEAD
git diff --stat origin/$BASE...HEAD
git diff --name-status origin/$BASE...HEAD
git diff origin/$BASE...HEAD
```

When a PR metadata command is provided, run it read-only. For branch targets, PR metadata is optional; if no PR exists, proceed using git context.

If `origin/$BASE` is missing or stale, use the best available base ref and explain the fallback in the packet.

Read the relevant source and test files directly so line references and explanations are grounded in code, not just patch text. For each important changed area, identify the changed line range and context that the reviewer should inspect in the packet.

## Build the Packet

Create a structured packet using the `ReviewPacketSchema` fields directly:

```ts
{
  target: {
    // command-provided target JSON plus optional headSha
  },
  source: {
    goal: "Context-first code walkthrough for <target>"
  },
  cards: [
    // Review cards, ordered from context/architecture to evidence/risks.
  ]
}
```

Recommended card sequence:

1. **Orientation** (`kind: "orientation"`)
   - What the work appears to accomplish in one or two sentences.
   - Problem or user/developer need it addresses.
   - Scope and complexity: files touched, subsystems affected, size of diff.
   - Keep this card short; it frames the review but is not the review surface.

2. **Architecture / lay of the land** (`kind: "architecture"`)
   - Relevant modules, ownership boundaries, data/control flow, extension points, commands, tools, UI, APIs, storage, or external services involved.
   - How the existing system is structured before this work.
   - Where the work fits into that structure.
   - Use prose in `body`, source line anchors in `references`, exact `quote` snippets where useful, and ASCII diagrams in `body` when helpful; do not include `references[].diff`.

3. **Behavior walkthrough** (`kind: "walkthrough"`)
   - The main runtime path from entrypoint to outcome.
   - Inputs, transformations, validation, side effects, and outputs.
   - Conditions that activate the new or changed behavior.
   - Use prose in `body`, source line anchors in `references`, exact `quote` snippets where useful, and ASCII diagrams in `body` when helpful; do not include `references[].diff`.

4. **Decisions and trade-offs** (`kind: "decision"`)
   - Design choices the work makes and why they matter.
   - Trade-offs, assumptions, compatibility constraints, and future implications.
   - Use prose in `body`, source line anchors in `references`, and exact `quote` snippets where useful; do not include `references[].diff`.

5. **Primary code changes / Git Diffs** (`kind: "diff-evidence"`)
   - Show the concrete changed code reviewers need to inspect.
   - This is the only card kind where `references[].diff` belongs. Provide structured intent; the code resolves it into git diffs for the packet.
   - Do not put raw git commands or pasted diff output in the packet when a structured diff reference can represent the evidence.
   - Group related changes rather than listing every touched file.
   - Explain why each diff matters in `whyRelevant`.

6. **Validation** (`kind: "validation"`)
   - Tests added or changed and scenarios covered.
   - Manual verification or commands that appear relevant.
   - Gaps where validation is missing or unclear.
   - Use prose in `body`, source line anchors in `references`, and exact `quote` snippets for test cases or command output where useful; do not include `references[].diff`.

7. **Risks** (`kind: "risk"`)
   - Correctness, UX, compatibility, migration, security, performance, operational, or maintainability risks.
   - Include impact and why the evidence points to the risk.
   - Use prose in `body`, source line anchors in `references`, and exact `quote` snippets where useful; do not include `references[].diff`.

8. **Open questions** (`kind: "open-question"`)
   - Questions for the author or reviewer that would change confidence or review focus.
   - Avoid questions already answered by metadata or code.
   - Use prose in `body`, source line anchors in `references`, and exact `quote` snippets where useful; do not include `references[].diff`.

Use multiple cards per kind when that improves clarity, but keep the packet concise enough for an interactive walkthrough.

## Reference Quality

Every reference must include a repo-relative `path` and explain why the code evidence matters using `whyRelevant`. Use `references[].diff` only in `diff-evidence` / Git Diffs cards, with structured fields that describe the desired evidence:

- `base`: base ref or commit for the comparison.
- `head`: optional head ref or commit; omit to compare the base against the checked-out review worktree.
- `path`: optional file path override; omit to use the reference `path`.
- `lineStart` and `lineEnd`: changed line range to focus.
- `contextLines`: surrounding unchanged lines to include.

The review packet tool resolves `references[].diff` into git diffs for `diff-evidence` cards. Provide structured intent, not raw git commands or pasted diff output. In all other card kinds, do not include `references[].diff`; put explanations, summaries, and ASCII diagrams in the card `body`, use source line anchors in `references`, and reserve `quote` for exact static snippets, PR metadata, config text, or command output. Do not use `quote` for prose paraphrase or generated ASCII diagrams.

Good `diff-evidence` references include:

```json
{
  "path": "path/to/file.ts",
  "lineStart": 42,
  "lineEnd": 58,
  "diff": {
    "base": "origin/main",
    "head": "HEAD",
    "lineStart": 42,
    "lineEnd": 58,
    "contextLines": 4
  },
  "whyRelevant": "This is the command entrypoint that starts the new walkthrough behavior, so it anchors the runtime path described in this card."
}
```

Reference guidance:

- Use structured diff references only in `diff-evidence` cards for changed-code evidence.
- In orientation, architecture, walkthrough, decision, validation, risk, and open-question cards, do not include `references[].diff`; use prose in `body`, source/test file line references, and exact `quote` snippets where useful.
- Use diff output to find what changed, then read source/test files directly to understand why it matters and to choose accurate line references.
- Keep evidence reviewable: include enough surrounding context to understand the change, but avoid dumping full files.
- Explain the significance of each reference, not just where it is.
- Cite PR metadata only when it materially affects orientation, scope, risk, or open questions.

## Submit the Walkthrough

After gathering context and building the packet, call `review_packet` with the structured packet object. Do not present a long standalone walkthrough first; the tool is the walkthrough entrypoint.

## Handle Feedback

After `review_packet` returns:

- Consolidate the returned feedback by card and category.
- Summarize next steps for the user.
- For `needs_explanation` or `question`, answer or identify the extra investigation needed.
- For `needs_code_change`, describe the requested change and affected files, but do not edit code automatically.
- If the user cancelled, acknowledge cancellation and offer to rebuild or narrow the packet.

Do not post GitHub comments, update PR metadata, or mutate the PR unless the user explicitly starts a separate workflow.
