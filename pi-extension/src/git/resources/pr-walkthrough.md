# PR Walkthrough — PR #{{PR_NUMBER}}

Prepare a context-first review packet for PR #{{PR_NUMBER}} on branch `{{BRANCH}}`, then call the `review_packet` tool. The goal is to help the user understand the change before inspecting individual diffs.

Do **not** treat the raw diff as the primary review object. Use diffs, logs, and file references as supporting evidence for the architecture, behavior, decisions, validation, and risks you explain.

## Target

Use this target when calling `review_packet`:

```json
{
  "kind": "pr",
  "prNumber": {{PR_NUMBER}},
  "branch": "{{BRANCH}}",
  "base": "{{BASE}}"
}
```

If you determine the current head SHA, include it as `headSha`.

## Step 1: Gather PR and Git Context

Collect enough context to explain the PR in plain language before drilling into files:

```bash
gh pr view {{PR_NUMBER}} --json number,title,body,state,author,headRefName,headRefOid,baseRefName,labels,assignees,reviewRequests,closingIssuesReferences,commits

git rev-parse HEAD
git log --oneline origin/{{BASE}}..HEAD
git diff --stat origin/{{BASE}}...HEAD
git diff --name-status origin/{{BASE}}...HEAD
git diff origin/{{BASE}}...HEAD
```

If `origin/{{BASE}}` is missing or stale, use the best available base ref and explain the fallback in the packet.

Also inspect the relevant source and test files directly so line references and explanations are grounded in code, not just patch text.

## Step 2: Build a Context-First Packet

Create a structured packet using the `ReviewPacketSchema` fields directly:

```ts
{
  target: {
    kind: "pr",
    prNumber: {{PR_NUMBER}},
    branch: "{{BRANCH}}",
    base: "{{BASE}}",
    headSha: "<optional current HEAD sha>"
  },
  source: {
    goal: "Context-first PR walkthrough for PR #{{PR_NUMBER}}"
  },
  cards: [
    // Review cards, ordered from context/architecture to evidence/risks.
  ]
}
```

Recommended card sequence:

1. **Orientation** (`kind: "orientation"`)
   - What the PR appears to accomplish in one or two sentences.
   - Problem or user/developer need it addresses.
   - Scope and complexity: files touched, subsystems affected, size of diff.

2. **Architecture / lay of the land** (`kind: "architecture"`)
   - Relevant modules, ownership boundaries, data/control flow, extension points, commands, tools, UI, APIs, storage, or external services involved.
   - How the existing system is structured before this PR.
   - Where the PR fits into that structure.

3. **Behavior walkthrough** (`kind: "walkthrough"`)
   - The main runtime path from entrypoint to outcome.
   - Inputs, transformations, validation, side effects, and outputs.
   - Conditions that activate the new/changed behavior.

4. **Decisions and trade-offs** (`kind: "decision"`)
   - Design choices the PR makes and why they matter.
   - Trade-offs, assumptions, compatibility constraints, and future implications.

5. **Diff evidence** (`kind: "diff-evidence"`)
   - The most important concrete code changes that support the earlier context.
   - Keep this as evidence, not the primary narrative.
   - Group related changes rather than listing every touched file.

6. **Validation** (`kind: "validation"`)
   - Tests added/changed and scenarios covered.
   - Manual verification or commands that appear relevant.
   - Gaps where validation is missing or unclear.

7. **Risks** (`kind: "risk"`)
   - Correctness, UX, compatibility, migration, security, performance, operational, or maintainability risks.
   - Include impact and why the evidence points to the risk.

8. **Open questions** (`kind: "open-question"`)
   - Questions for the author or reviewer that would change confidence or review focus.
   - Avoid questions already answered by PR metadata or code.

Use multiple cards per kind when that improves clarity, but keep the packet concise enough for an interactive walkthrough.

## Reference Quality

Every reference must explain why the code evidence matters using `whyRelevant`.

Good references include:

```json
{
  "path": "path/to/file.ts",
  "lineStart": 42,
  "lineEnd": 58,
  "quote": "optional short quote",
  "whyRelevant": "This is the command entrypoint that starts the new walkthrough behavior, so it anchors the runtime path described in this card."
}
```

Reference guidance:

- Prefer source/test file line references over raw diff snippets.
- Use diff output to find what changed, then read files to understand why it matters.
- Explain the significance of each reference, not just where it is.
- Cite PR metadata only when it materially affects orientation, scope, risk, or open questions.

## Step 3: Call `review_packet`

After gathering context and building the packet, call `review_packet` with the structured packet object. Do not present a long standalone walkthrough first; the tool is the walkthrough entrypoint.

## Step 4: Handle Feedback

After `review_packet` returns:

- Consolidate the returned feedback by card and category.
- Summarize next steps for the user.
- For `needs_explanation` or `question`, answer or identify the extra investigation needed.
- For `needs_code_change`, describe the requested change and affected files, but **do not edit code automatically**.
- If the user cancelled, acknowledge cancellation and offer to rebuild or narrow the packet.

Do not post GitHub comments, update PR metadata, or mutate the PR unless the user explicitly starts a separate workflow.
