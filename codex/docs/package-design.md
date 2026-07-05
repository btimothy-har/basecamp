# Codex Package Design

Snapshot date: 2026-07-05.

This document describes the intended shape of the Codex package under `codex/`.
The package is not a Pi compatibility layer and should not be organized as a
line-by-line port of Pi extension behavior. It is a Codex-native package that
uses Codex's own primitives: skills, custom agents, MCP servers, hooks,
settings, profiles, and project instructions.

Pi remains useful as prior art. Existing Basecamp Pi features can suggest
workflows, safety policies, and project-memory needs. But each feature should be
re-designed for Codex rather than copied across runtime boundaries.

## Direction

The Codex package should stand on its own. It should not depend on Basecamp core
runtime state, Pi registries, or Pi session hooks. Shared knowledge can be
copied, adapted, or referenced, but Codex-facing files should read as native
Codex guidance.

Codex does not currently expose a first-class API for arbitrary in-process
commands, tools, or custom modes in the way Pi packages do. The closest native
equivalents are:

- tools: MCP servers and MCP tools
- commands/workflows: skills
- specialist behavior: custom agents
- lifecycle behavior: hooks
- durable defaults: settings, profiles, and project instructions

Deprecated custom prompts can approximate slash-command ergonomics, but the
preferred path is to use skills for reusable workflows.

## Placement Rules

### Skills

Use a skill when the feature is primarily model behavior, a repeatable workflow,
or domain-specific operating guidance.

Good skill candidates:

- Python development guidance
- data warehousing guidance
- marimo notebook guidance
- PR creation and PR description workflow
- code walkthrough workflow
- review-packet synthesis workflow
- planning and implementation-plan workflow
- copilot/workstream briefing workflow
- project memory usage conventions

Skills should avoid owning mutable state. If a workflow needs durable reads or
writes, pair the skill with an MCP server that owns the data boundary.

### MCP Servers

Use an MCP server when the feature needs an executable tool, external data,
structured state, or a controlled write boundary.

Good MCP candidates:

- Logseq/project memory reads and writes
- BigQuery or warehouse query tools
- workstream launch records and lookups
- structured review packet generation if it needs repo/GitHub/state access
- project registry lookup if Codex needs more than static instructions
- agent daemon or companion APIs, if those continue as separate services

The Logseq copilot case should prefer an MCP over broad filesystem writes. The
MCP can expose semantic operations such as `read_repo_cockpit`,
`update_repo_cockpit`, `list_work_dossiers`, `read_work_dossier`,
`update_work_dossier`, and `search_repo_memory`. That keeps page naming,
locking, formatting, and safety rules outside the model's raw file-editing path.

Use `--add-dir` or additional writable roots only when raw filesystem access is
the intended interface.

### Hooks

Use a hook when the feature must react to a Codex lifecycle event or tool-use
boundary.

Good hook candidates:

- bash or shell command review
- protected-checkout guardrails
- prompt or secret scanning before submission
- session start context hydration
- post-tool validation or telemetry
- session stop snapshots

Hooks should stay small and deterministic. If they need complex domain logic,
delegate to a local command or service and keep the hook as the lifecycle
adapter.

### Settings And Profiles

Use settings when the feature is a persistent Codex default, permission policy,
or launch-time operating environment.

Good settings candidates:

- branch prefix
- commit-message generation prompt
- PR-description generation prompt
- force-push policy
- model and reasoning defaults
- sandbox and approval policy
- MCP server registration
- hook registration
- project trust
- local environment setup scripts
- additional writable roots for specific profiles

Profiles are the closest Codex equivalent to launch-time modes. A profile can
bundle model, sandbox, approval policy, MCP availability, and instructions for a
particular operating stance.

### Custom Agents

Use a custom agent when the feature is a bounded specialist role that should
investigate or critique without taking over the main thread.

Current useful agents:

- security specialist
- testing specialist
- documentation specialist
- code clarity specialist
- devil's advocate

Potential additions:

- copilot memory scout
- PR reviewer
- migration planner
- data/warehouse reviewer

Agents should report findings and recommendations. The main thread should keep
final synthesis and implementation ownership.

## Modes

Pi-style custom modes should not be modeled as Codex product modes. Codex has
built-in modes such as Local, Worktree, Cloud, Plan mode, and Goal mode, but the
available extension surfaces do not currently include arbitrary user-defined
selectable modes.

Represent mode-like behavior as a Codex package bundle:

- a skill for the workflow
- optional custom agents for specialist work
- MCP servers for data and tools
- settings or profiles for permissions and model defaults
- hooks for lifecycle enforcement

For example:

```text
copilot =
  skill: copilot workflow
  agents: memory scout, reviewer, implementation worker
  MCP: Logseq project memory
  profile/settings: project root, optional writable roots, approval policy
  hooks: shell review and session snapshots
```

## Copilot And Logseq

Codex's project-scoped threads make the copilot/workstream concept clean. The
thread already has a project identity, working directory, history, approvals,
and optional worktree. The missing piece is durable project memory.

There are two viable paths:

1. Add the Logseq graph as an additional directory or writable root for the
   copilot session.
2. Expose Logseq through an MCP server.

Prefer the MCP path for the default package. It gives Codex semantic memory
operations without granting broad graph writes. A special profile can still add
the Logseq directory for maintenance workflows that intentionally edit the graph
as files.

## Initial Package Shape

The `codex/` package should contain:

- `projection.toml`: package manifest used by the current installer
- `instructions/`: durable Codex operating guidance
- `agents/`: custom agent definitions
- `docs/`: package design notes
- future `skills/` or skill source references as the package gains its own
  workflows
- future `hooks/` if lifecycle behavior becomes Codex-native
- future MCP package metadata when a Codex-native tool boundary is added

The package should stay independent from Basecamp core. The installer may live
in Basecamp while this is incubating, but the Codex package should be portable
enough to split out later.

## Open Decisions

- Whether to create first-class Codex-native skills for PR creation, review
  packets, planning, and copilot now, or continue symlinking existing engineering
  skills first.
- Whether the Logseq integration should be a small local MCP server in this
  package or a separate package that this package registers.
- Whether any current Pi bash-reviewer behavior should become Codex hooks, and
  which checks should remain approval policy rather than custom code.
- Whether profiles should be generated by `basecamp sync codex` or documented as
  manual user configuration.
