# pi-swarm extension package

This package owns the TypeScript runtime for Basecamp async-agent features: public daemon tools, launch policy, daemon client/reporting code, and dependency-injected registration helpers.

`registerPiSwarm(pi, deps)` hosts the async-only surface for this domain: the agent catalog provider plus daemon client, tools, and reporting.

