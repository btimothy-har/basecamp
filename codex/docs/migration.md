# Codex Package Migration Plan

Snapshot date: 2026-07-05.

This plan describes how to make `codex/` the primary home for Codex-facing
engineering workflows. The target is a self-contained Codex package with its own
skills, agents, settings, hooks, and MCP boundaries. Pi remains useful as prior
art and as an existing production system during the transition, but the Codex
package should not depend on Pi runtime APIs or Basecamp core runtime state.

## Goals

- Make `codex/` understandable as a standalone package.
- Move Codex-facing behavior into Codex-native surfaces.
- Preserve current productive workflows while replacing Pi-specific assumptions.
- Keep the migration reversible until the Codex package has proven itself in
  normal engineering sessions.
- Prefer semantic tools and workflows over broad filesystem access.

## Non-Goals

- Rebuild Pi inside Codex.
- Recreate Pi command, mode, registry, or session-hook APIs.
- Replace Codex-owned app features such as Worktree mode, Plan mode, approvals,
  subagents, browser use, Git UI, or app worktrees.
- Move every Basecamp feature at once.
- Make `basecamp sync codex` the long-term packaging answer before the package
  shape is settled.

## Target Shape

The package should eventually contain:

- `instructions/`: durable Codex operating guidance.
- `agents/`: Codex custom agent definitions.
- `skills/`: Codex-native workflow and domain skills.
- `hooks/`: small lifecycle adapters for safety and session behavior.
- `mcp/`: local MCP servers or registration metadata for structured tools.
- `profiles/` or documented settings snippets for launch-time operating stances.
- `docs/`: package design, migration, and operating notes.

The current `projection.toml` can remain as the installer manifest while this
incubates. Treat it as a compatibility detail of the installer, not as the
conceptual model for the package.

## Migration Principles

- Codex-first: choose the Codex primitive that fits the job, even when the Pi
  implementation used a different shape.
- Package-first: new Codex behavior belongs under `codex/` unless it is truly a
  reusable non-Codex library.
- Semantic boundaries: use MCP tools for durable data and external systems.
- Thin hooks: keep hooks deterministic and small; move domain logic elsewhere.
- Skills over prompts: use skills for reusable workflows instead of deprecated
  custom prompts.
- Reversible rollout: keep Pi workflows available until Codex equivalents have
  been validated in real sessions.

## Phase 0: Stabilize The Package Boundary

Objective: make `codex/` clearly read as the Codex package.

Tasks:

- Keep model-facing instructions native to Codex.
- Keep docs explicit that Pi is prior art, not the package frame.
- Rename installer internals only after the external package language has
  settled.
- Decide whether future package assets should live directly in `codex/skills`,
  `codex/hooks`, and `codex/mcp`, or continue referencing canonical sources
  elsewhere during incubation.

Exit criteria:

- `codex/README.md` explains the package without relying on Pi terminology.
- `codex/docs/package-design.md` explains where skills, MCPs, hooks, settings,
  and agents belong.
- New contributors can understand what `codex/` owns without reading Pi package
  internals first.

## Phase 1: Inventory Current Codex-Facing Behavior

Objective: identify what already works in Codex and what needs a native home.

Inventory:

- durable operating guidance in `codex/instructions/`
- custom specialist agents in `codex/agents/`
- symlinked engineering skills from `pi-engineering/skills/`
- `basecamp sync codex` installer behavior
- user-level Codex settings currently required for the workflow

Tasks:

- Create a table of current user-visible Codex behaviors and their source files.
- Mark each behavior as keep, rewrite as skill, rewrite as MCP, rewrite as hook,
  move to settings, or retire.
- Identify which workflows still depend on Pi-only concepts such as custom
  commands, modes, registries, session state, or tool-call hooks.

Exit criteria:

- Every Codex-facing behavior has an owner and intended Codex surface.
- No migration task is blocked on an implicit Pi concept.

## Phase 2: Promote Core Workflows Into Skills

Objective: make workflow invocation skill-driven.

Initial skill candidates:

- copilot/workstream briefing
- implementation planning
- PR description and PR creation preparation
- code walkthrough
- review packet synthesis
- project memory usage conventions

Tasks:

- Create Codex-native skill specs for the highest-value workflows.
- Keep each skill instruction-focused unless it needs executable data access.
- Reference MCP tools in skills only after the MCP boundary exists.
- Prefer small workflow skills over one large omnibus skill.
- Preserve existing engineering domain skills for Python, data warehousing, and
  marimo while deciding whether they should remain shared or become package
  assets.

Exit criteria:

- A user can intentionally invoke the main workflows through skills.
- Skills do not require Pi commands, Pi tool registries, or Pi session state.
- Workflow docs explain what the skill owns and what external tools it expects.

## Phase 3: Add Project Memory Through MCP

Objective: make durable project memory available through semantic tools.

Default direction:

- Build a small Logseq/project-memory MCP server.
- Register the MCP in Codex settings or package metadata.
- Keep raw Logseq directory writes out of the default workflow.

Candidate tools:

- `read_repo_cockpit`
- `update_repo_cockpit`
- `list_work_dossiers`
- `read_work_dossier`
- `update_work_dossier`
- `search_repo_memory`
- `record_workstream_event`

Tasks:

- Define the page schema and naming conventions the MCP owns.
- Define read/write safety rules, locking behavior, and conflict handling.
- Add dry-run or preview support for writes where practical.
- Add tests for parsing, formatting, and idempotent updates.
- Document the exceptional profile that grants raw Logseq filesystem writes for
  graph maintenance.

Exit criteria:

- Copilot workflows can read and update project memory without raw graph access.
- Memory writes are structured, auditable, and safe to retry.
- Users can still opt into raw filesystem access for maintenance workflows.

## Phase 4: Move Safety Boundaries Into Settings And Hooks

Objective: replace Pi-side safety hooks with Codex-native settings and small
hooks where needed.

Settings candidates:

- sandbox mode
- approval policy
- command allow/deny rules
- branch prefix
- force-push policy
- generated commit-message prompt
- generated PR-description prompt
- MCP registrations
- trusted project configuration

Hook candidates:

- shell command review for risky commands
- protected checkout guard
- secret or prompt scanning
- session start context hydration
- session stop snapshot

Tasks:

- Prefer built-in Codex permissions and approvals before adding custom hooks.
- Implement hooks only for gaps that settings cannot express.
- Keep hook handlers small and auditable.
- Add tests or fixture-driven checks for hook command behavior.
- Document how hooks behave in main sessions and subagents.

Exit criteria:

- Risky shell/Git behavior is covered by settings, approvals, or hooks.
- Protected checkout behavior has a clear Codex-native enforcement point.
- Hook behavior can be disabled or rolled back independently.

## Phase 5: Define Profiles For Operating Stances

Objective: replace custom-mode thinking with Codex profiles and workflow skills.

Candidate profiles:

- default engineering
- copilot with project memory MCP
- graph maintenance with raw Logseq write access
- review-heavy or high-scrutiny mode
- fast exploratory mode

Tasks:

- Decide which profiles should be generated by the installer and which should be
  documented snippets.
- Keep profiles focused on launch-time concerns: model, reasoning, sandbox,
  approvals, MCPs, writable roots, and instructions.
- Pair each profile with the skill or workflow it is meant to support.

Exit criteria:

- Users can choose an operating stance without requiring custom Codex modes.
- Profile differences are easy to audit.
- High-risk profiles, such as raw Logseq writes, are opt-in.

## Phase 6: Update Installer And Packaging

Objective: make installation match the package shape.

Tasks:

- Extend the manifest only after assets have stable homes.
- Add install support for package-owned skills.
- Add install support for hooks if hooks become part of the package.
- Add MCP registration support only after the first MCP server contract is
  stable.
- Consider renaming installer internals away from projection terminology.
- Keep managed markers and preflight checks so user-owned Codex files are not
  overwritten unexpectedly.

Exit criteria:

- `basecamp sync codex` installs the package assets users need.
- The installer remains conservative around user-owned files.
- The package could be split out later without changing model-facing behavior.

## Phase 7: Validate In Real Codex Sessions

Objective: prove the package works in ordinary engineering work.

Validation scenarios:

- start a new Codex thread in an existing repo
- run a planning workflow through a skill
- implement a small code change using the package guidance
- ask specialist agents for review
- create a PR description using the Codex workflow
- use project memory through MCP in a copilot session
- run with a worktree and confirm package behavior remains project-scoped
- attempt a risky command and confirm the expected safety boundary triggers

Exit criteria:

- The package supports a full issue-to-PR workflow without Pi.
- Project memory access works without raw graph edits in the default path.
- Hooks and settings do not create surprising friction.
- Rollback is documented and tested enough for regular use.

## Phase 8: Cutover And Deprecation

Objective: make Codex the primary home for Codex-facing workflows.

Tasks:

- Mark Codex-native workflows as canonical for Codex users.
- Stop adding new Codex-facing behavior to Pi packages.
- Keep Pi implementations only where Pi remains an active target.
- Update top-level docs to distinguish Pi support from Codex package support.
- Remove or retire duplicated guidance after Codex usage has stabilized.

Exit criteria:

- Codex users no longer need to understand Pi internals to use the workflow.
- New Codex behavior lands in `codex/` by default.
- Remaining Pi behavior has an explicit reason to stay in Pi.

## Suggested First Cut

The first useful slice should be small:

1. Keep current instructions, agents, and symlinked engineering skills.
2. Add a Codex-native copilot/workstream skill.
3. Add a Codex-native PR description skill.
4. Design the Logseq MCP contract without implementing it yet.
5. Document one `copilot` profile that enables the future MCP and avoids raw
   graph writes by default.

This gives the package an identity without forcing the whole migration through
one large rewrite.

## Risks

- Too much direct copying from Pi could leave Codex feeling like a hosted Pi
  adapter rather than its own package.
- Broad filesystem access to Logseq could corrupt project memory or make writes
  hard to audit.
- Hooks could duplicate behavior Codex already handles through approvals and
  sandboxing.
- One large skill could become a new monolithic prompt layer.
- Installer changes could overwrite user-owned Codex configuration if preflight
  checks are weakened.

## Open Decisions

- Which workflow skill should be created first: copilot, PR description, planning,
  or review packet?
- Should the Logseq MCP live inside this package or as a separate package that
  this package registers?
- Should generated profiles be installed automatically or documented for manual
  opt-in?
- Should `projection.toml` be renamed once installer internals are updated, or
  remain as a stable implementation detail?
