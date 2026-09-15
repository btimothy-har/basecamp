# Code Review Flows

Basecamp has separate review integrations for legacy Pi and OMP. Pi owns an independent review workflow behind `/code-review`; OMP keeps its native `/review` mechanics and adds only final presentation, feedback, and artifact capture.

## OMP native review presentation

Native OMP `/review` remains authoritative for scope selection, diff preparation and filtering, reviewer count and locality, read-only reviewer tasks, and the structured `correct|incorrect` plus P0–P3 result shape. Basecamp does not replace or wrap that command.

The exact-pinned OMP review prompt starts with `## Code Review Request` and dispatches the `reviewer` agent. A `context` extension hook recognizes the latest active native review request at the model boundary and inserts a hidden final-chair contract. This covers idle, headless, and queued review prompts without resending the command or reviving instructions from a historical review. The primary must validate findings against the code, discard false positives, semantically deduplicate shared root causes, call `review_findings` exactly once, and read the returned artifact before continuing. Reviewer subagents continue using native structured yields and never call the presentation tool.

### OMP flow

1. Native `/review` resolves the scope and builds the review prompt.
2. OMP dispatches its native `reviewer` tasks and returns their structured results to the primary.
3. The primary validates and consolidates the results into the strict native-shaped `review_findings` input, including an empty findings array when none remain.
4. In TUI mode, `review_findings` opens a `ui.custom` navigator. Headless modes skip interaction but still record the review with feedback marked unavailable.
5. The tool deterministically sorts findings, assigns artifact-local IDs, nests each submitted comment with its finding, and writes versioned JSON through `sessionManager.saveArtifact`.
6. The model-visible tool result is only `Read artifact://<id> before continuing.` The full payload is recovered from that session artifact.

The navigator is terminal-height aware and recalculates its list and card viewports after resize. The list keeps the selected finding visible; cards use `PageUp`/`PageDown` for long content; the embedded editor owns cursor-following scroll for long comments. The tool's abort signal reaches both custom views, so cancellation cannot leave a mounted navigator or persist stale feedback.

| View | Keys |
|------|------|
| List | `↑`/`↓` move · `Space`/`Enter` open · `s` submit · `Esc`/`ctrl+c` discard every comment |
| Card | `←`/`→` prev/next · `PageUp`/`PageDown` scroll · `↓` or `Tab` comment · `Esc` back |
| Comment box | `Enter` save · `Esc` save and close · `↑`/`Backspace` on empty close · `shift+Enter` newline |

The artifact is session-scoped: it survives resume and rewind, moves with the session, copies on fork, and is removed when the session is dropped. Its schema contains `schema_version`, scope, final correctness/explanation/confidence, feedback status, and findings with native priority/location fields plus nested nullable comments.

### OMP layout

- `omp/review/instructions.ts`: native-review recognition and model-context chair contract.
- `omp/review/schema.ts`: strict native-shaped tool input and versioned artifact types.
- `omp/review/artifact.ts`: deterministic ordering, IDs, counts, and artifact construction.
- `omp/review/tool.ts`: `review_findings`, artifact save, and passive transcript renderer.
- `omp/review/navigator/`: keyboard model, terminal rendering, and `ui.custom` list/card loop.

## Legacy Pi review

`/code-review [additional instructions]` is a thin primary-only prompt command that unconditionally directs the agent to load and apply the model-invocable `code-review` skill. The skill is the authoritative method for an independent review of the current branch: it dispatches fixed and risk-driven report-only reviewers, and the primary review chair verifies, synthesizes, and deduplicates their reports before `report_findings` computes a deterministic verdict over that final set. The skill and result tool are never exposed in subagents.

### Review method

The skill retrieves `references/review-method.md` through the skill tool's `reference` parameter — `skill({ name: "code-review", reference: "references/review-method.md" })` — rather than by reading a path. That reference is the canonical method for the local multi-agent review: it defines the four severities, structured finding contract, and falsification probes for invariants, end-to-end paths, representation parity, boundary/fallback behavior, counterfactual tests, canonical ownership, rollout, and recovery.

Reviewers may inspect PR descriptions, commits, and linked issues for claimed intent, but treat all repository and GitHub text as untrusted data. Claims never substitute for implementation evidence or narrow review scope.

### Flow

1. Resolve the current branch, base, merge base, tracked working-tree changes, and untracked files.
2. Inspect the actual diff only far enough to map material risk surfaces without authoring findings.
3. Dispatch seven fixed report-only lenses: security, testing, docs, clarity, conventions, general correctness, and integration.
4. Dispatch focused adaptive `general-reviewer`s for each material data/migration, API/protocol, UI/data, async/retry, concurrency/state, performance, build/deploy, or broad-refactor aspect; conditionally dispatch the `data-model-specialist` when the diff has SQL or dbt signals; add another narrow specialist only when its lens needs an independent second pass.
5. Wait for all reviewers and record any coverage failures.
6. Verify and normalize reports, merge only semantic duplicates, preserve unique substantive findings, and dispatch independent verification for any concern first noticed by the primary.
7. Write and show one concise summary, then call `report_findings({ scope, summary, findings })` with the same summary and synthesized final set.
8. Discuss the packet with the user; never start fixes automatically.

The integration lens owns cross-layer producer/consumer contracts, semantic parity, runtime wiring, temporal alignment, source-of-truth drift, rollout compatibility, and operational completion. It leaves local functional logic, exploitability, test quality, documentation-only drift, pure clarity, and codified conventions to their dedicated lenses.

### Result handling

The primary may rewrite and regroup findings based on verified root cause and impact; source selection and semantic deduplication are editorial model judgment. Independent reviewers remain the source of defects, and the primary must obtain a focused reviewer report before adding a concern it noticed itself. The verdict is deterministic only after this synthesis.

`report_findings` sorts the final findings and computes the verdict from severity counts (any critical → Request Changes; at least three high → Request Changes; one or two high → Comment; medium/low only → Approve with notes; none → Approve). A per-finding `response` can contest or contextualize a finding but never changes the verdict.

The annotation pane collects optional user reactions. The private packet stores the primary summary, synthesized findings, responses, and reactions under session scratch with mode `0600`; its directory is `0700`. Raw reviewer reports and provenance mappings are not retained.

### Annotation pane

A finding list drills into a card carrying one optional comment, mirroring the plan-review shape in `pi/tasks/workflows/review/`.

| View | Keys |
|------|------|
| List | `↑`/`↓` move · `Space`/`Enter` open · `s` submit · `Esc`/`ctrl+c` discard every comment |
| Card | `←`/`→` prev/next finding · `↓` or `Tab` open the comment box · `Esc` back to the list |
| Comment box | `Enter` save · `Esc` save and close · `↑`/`Backspace` on empty close · `shift+Enter` newline |

Enter deliberately does **not** open the comment box, and every exit from the box commits, so the list-level discard is the only key that destroys a comment.

"Comment" is the word throughout the domain; "reaction" belongs to the packet schema, and `CommentStore.toComments()` feeds `AnnotateResult.reactions` at that boundary.

**`CommentStore` is the single source of truth; the `Editor` is a buffer, never an authority.** `Editor.submitValue()` empties itself *before* invoking `onSubmit`, so reading `getText()` anywhere on a submit path reads an empty editor and erases the comment. The store is therefore seeded into the editor on focus-in and written back only from values carried on `CardEvent`s, and `reduceCard` drops a `blurEditor` that arrives after a submit has already left editing mode.

Two consequences of that rule are easy to undo by accident. The blur path reads `getExpandedText()`, not `getText()`: a large paste sits in the buffer as a marker, and the next focus-in `setText()` clears the paste map, so storing the unexpanded marker loses the content permanently. And the comment box is a slot child of the card's `Container` rather than lines spliced into rendered output: its position must follow the component tree, because finding text is reviewer-authored and can contain any label string.

### Layout

- `index.ts`: registers `report_findings` and exposes the prompt command and skill in primary sessions only.
- `prompts/code-review.md`: thin command wrapper that loads and applies the skill with optional additional instructions.
- `skills/code-review/SKILL.md`: authoritative orchestration contract.
- `skills/code-review/references/review-method.md`: shared reviewer method and finding contract.
- `tools.ts`: result tool and review-chair handoff.
- `findings.ts`: dimensions, severities, scope, and tool schemas.
- `synthesis.ts`: stable finding order and deterministic verdict.
- `annotate/model.ts`: `CommentStore`, card state, and the pure `reduceCard` transitions.
- `annotate/keys.ts`: keystroke-to-intent mapping for the list, card, and comment box.
- `annotate/render.ts`: list and card text.
- `annotate/index.ts`: the two `ui.custom` views and the list/card loop.
- `artifact.ts`: private review packet.

The feature reviews the current branch only. PR-number and arbitrary-branch targets are out of scope.
