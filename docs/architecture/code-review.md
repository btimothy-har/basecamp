# Code Review Flows

Basecamp has separate review integrations for legacy Pi and OMP. Pi owns an independent review workflow behind `/code-review`; Basecamp owns OMP's `/review` command, skill-guided orchestration, and final presentation, feedback, and artifact capture.

## OMP review workflow

Basecamp's loaded OMP extension registers `/review` with three scopes: a committed comparison against a selected base branch, one specific commit, or custom instructions. The extension handler wins dispatch precedence over OMP's bundled command, while a public autocomplete-provider wrapper keeps only Basecamp's duplicate-name choice visible in the TUI. Branch comparisons resolve the live invocation worktree, pin the merge base and current head to full revisions, and exclude the current branch from the base picker. Commit reviews pin the selected commit. Custom reviews preserve the submitted instructions for model-resolved inspection. There is intentionally no uncommitted mode.

The command sends a thin prompt containing the authoritative scope and an explicit `skill://code-review` reference through `pi.sendUserMessage`. This enters OMP's normal prompt lifecycle without re-entering slash-command expansion. The skill owns scope fidelity, risk-based native reviewer selection, synthesis, overall and per-finding recommendations, and the single `review_findings` presentation call. OMP's native `reviewer` agent remains authoritative for finding method, evidence, priorities, and structured output. Committed scopes exclude index and working-tree changes; an empty scope stops without meaningless reviewer dispatch.

### OMP flow

1. Basecamp `/review` captures the live invocation directory, resolves the selected scope, and sends the skill-directed context.
2. The primary loads the review skill, inspects the exact scope, and chooses independent reviewer coverage proportionate to its material risks.
3. OMP's native `reviewer` tasks return structured results; the primary validates and consolidates them into `review_findings`: native verdict, confidence, priority, and location fields plus Basecamp-owned overall and per-finding recommendations. Finding bodies own evidence and impact; recommendations own what the user should do. Paths are normalized to repository-relative form, and an empty findings array is included when none remain.
4. In TUI mode, `review_findings` opens a `ui.custom` navigator. Its height-aware header prioritizes a preview of the overall recommendation and shows the explanation when space permits, while each scrollable finding card carries its own recommendation. Headless modes skip interaction but still record the review with feedback marked unavailable.
5. The tool deterministically sorts findings, assigns artifact-local IDs, nests each submitted comment with its finding, and writes schema-versioned JSON through OMP storage primitives.
6. In persistent sessions, the model-visible tool result is only `Read artifact://<id> before continuing.` In `--no-session` mode, where OMP cannot resolve its in-memory artifact IDs through `artifact://`, the tool writes the same JSON to the content-addressed blob store and returns its readable path. The passive transcript renderer shows the full explanation and overall recommendation in both modes, including clean reviews that do not open the navigator.

The navigator recalculates its layout after every resize. The header is wrapped to terminal width, capped by available height, and its actual rendered height determines the finding-list budget. Cards use `PageUp`/`PageDown` for long bodies and recommendations; the embedded editor owns cursor-following scroll for long comments. The tool's abort signal reaches both custom views, so cancellation cannot leave a mounted navigator or persist stale feedback.

| View | Keys |
|------|------|
| List | `↑`/`↓` move · `Space`/`Enter` open · `s` submit · `Esc`/`ctrl+c` discard every comment |
| Card | `←`/`→` prev/next · `PageUp`/`PageDown` scroll · `↓` or `Tab` comment · `Esc` back |
| Comment box | `Enter` save · `Esc` save and close · `↑`/`Backspace` on empty close · `shift+Enter` newline |

Persistent-session artifacts survive resume and rewind, move with the session, copy on fork, and are removed when the session is dropped. The no-session blob fallback instead follows OMP's content-addressed blob garbage-collection lifecycle. Schema version 2 contains scope, final correctness/explanation/recommendation/confidence, feedback status, and findings with native priority/location fields, a required recommendation, and nested nullable comments. Recommendation text is presentation guidance; priority counts and the overall verdict remain determined solely by their native fields.

### OMP layout

- `omp/review/command.ts`: extension command registration, scope UI, and live-worktree Git resolution.
- `omp/review/autocomplete.ts`: duplicate-name TUI filtering over OMP's public provider-composition API.
- `omp/review/request.ts`: thin skill trigger and authoritative scope context.
- `omp/skills/code-review/SKILL.md`: OMP review-chair orchestration, synthesis, recommendations, and presentation guidance.
- `omp/review/schema.ts`: strict native-fields-plus-recommendations tool input and versioned artifact types.
- `omp/review/artifact.ts`: deterministic ordering, IDs, counts, and artifact construction.
- `omp/review/tool.ts`: `review_findings`, artifact save, and passive transcript renderer.
- `omp/review/paths.ts`: in-repository finding-path normalization; OMP's `findRepoRoot` owns root discovery.
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
