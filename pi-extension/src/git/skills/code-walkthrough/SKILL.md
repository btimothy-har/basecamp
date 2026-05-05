---
name: code-walkthrough
description: "Create a context-first code walkthrough review packet for a branch or PR, with architecture, decisions, diff evidence, validation, and targeted feedback."
---

# Code Walkthrough

Create a code-focused review packet for a branch or pull request, then call `review_packet`. The goal is to help the user review the actual code with enough context to understand why the changes matter.

Keep orientation brief. The walkthrough is for code review, not prose review: every substantive claim should be backed by visible code or diff evidence. Use narrative to explain significance, but make concrete changed code the review surface.

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

Read the relevant source and test files directly so line references and explanations are grounded in code, not just patch text. For each important changed area, capture a short code or diff excerpt that the reviewer can inspect in the packet.

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

2. **Primary code changes** (`kind: "diff-evidence"`)
   - Show the concrete changed code reviewers need to inspect.
   - Use `references[].quote` for changed hunks, before/after snippets, or compact code excerpts.
   - Group related changes rather than listing every touched file.
   - Explain why each excerpt matters in `whyRelevant`.

3. **Architecture / lay of the land** (`kind: "architecture"`)
   - Relevant modules, ownership boundaries, data/control flow, extension points, commands, tools, UI, APIs, storage, or external services involved.
   - How the existing system is structured before this work.
   - Where the work fits into that structure.

4. **Behavior walkthrough** (`kind: "walkthrough"`)
   - The main runtime path from entrypoint to outcome.
   - Inputs, transformations, validation, side effects, and outputs.
   - Conditions that activate the new or changed behavior.

5. **Decisions and trade-offs** (`kind: "decision"`)
   - Design choices the work makes and why they matter.
   - Trade-offs, assumptions, compatibility constraints, and future implications.

6. **Validation** (`kind: "validation"`)
   - Tests added or changed and scenarios covered.
   - Manual verification or commands that appear relevant.
   - Gaps where validation is missing or unclear.

7. **Risks** (`kind: "risk"`)
   - Correctness, UX, compatibility, migration, security, performance, operational, or maintainability risks.
   - Include impact and why the evidence points to the risk.

8. **Open questions** (`kind: "open-question"`)
   - Questions for the author or reviewer that would change confidence or review focus.
   - Avoid questions already answered by metadata or code.

Use multiple cards per kind when that improves clarity, but keep the packet concise enough for an interactive walkthrough.

## Reference Quality

Every reference must explain why the code evidence matters using `whyRelevant`. For code review, most references should also include `quote` with an explicit code or diff excerpt. Do not use `quote` for a prose paraphrase.

Good references include:

```json
{
  "path": "path/to/file.ts",
  "lineStart": 42,
  "lineEnd": 58,
  "quote": "if (changed) {\n  return newBehavior();\n}",
  "whyRelevant": "This is the command entrypoint that starts the new walkthrough behavior, so it anchors the runtime path described in this card."
}
```

Reference guidance:

- Prefer source/test file line references plus short code excerpts over prose-only references.
- Use diff output to find what changed, then read files to understand why it matters.
- For complex changes, include compact before/after or changed-hunk snippets in `quote`.
- Keep excerpts reviewable: include enough surrounding lines to understand the change, but avoid dumping full files.
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
