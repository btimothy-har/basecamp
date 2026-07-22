# ui (core submodule)

Framework UI for a basecamp session — status footer, title auto-naming, and the interactive mode editor. Lives in `core` (`pi/core/ui/`) and is registered by `registerCore` alongside core's other in-session surfaces (`escalate`, `capabilities`), on the principle that *framework* chrome belongs with the framework. Feature-specific widgets such as task cards and agent rows stay with their owning domains.

## What it does

- **Status footer**: renders cwd, worktree label, branch, agent mode, invoked skills, context usage, and extension statuses as a persistent UI frame
- **Title auto-naming**: generates short session titles from conversation context using a low-cost model
- **Mode editor**: interactive picker for switching between agent modes (analysis/planning/work)
- **Mode styles**: color/label palette mapping for each agent mode

## Dependencies

- **core** (sibling modules, via relative imports): agent-mode state, session/workspace state, skill-tracker, and model-alias resolution. Consumed from outside `core` only as `formatTitle` (swarm's daemon widget), via `#core/ui/index.ts`.
