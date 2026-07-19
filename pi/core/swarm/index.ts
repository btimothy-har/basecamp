import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAgentCatalog } from "./agents/index.ts";
import { registerAgentSurfaces } from "./agents/surfaces.ts";

/**
 * The agent-dispatch primitive — core's adapter for the async-agent runtime,
 * a peer of `core/hub`. Registers the builtin agent catalog provider and the
 * session surfaces (dispatch/ask/cancel/peer tools, run reporter, active-agents
 * widget) over the core hub connection. Registered by `registerCore`.
 *
 * The `/code-review` and workstream *features* are separate domains
 * (`pi/code-review/`, `pi/workstreams/`) that consume this via
 * `#core/swarm/agents/*`.
 */
export default function registerSwarm(pi: ExtensionAPI): void {
	registerAgentCatalog();
	registerAgentSurfaces(pi);
}
