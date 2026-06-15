# pi-swarm

`pi-swarm` is the top-level bounded context for async-agent behavior.

It owns:

- `protocol/` — protocol docs and frame fixture assets for the daemon protocol surface.
- `extension/` — TypeScript package for Pi-side agent tools, launch policy, daemon client code, and reporter code.
- `cli/` — Python package for daemon runtime and CLI components.

`basecamp-cli` and `pi-extension` remain the public package and adapter entry points in this phase.
