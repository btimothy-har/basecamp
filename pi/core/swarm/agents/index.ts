/**
 * Agent catalog registration.
 */

import { registerAgentCatalogProvider } from "./catalog.ts";
import { discoverAgents } from "./discovery.ts";
import type { AgentConfig } from "./types.ts";

export function registerAgentCatalog(): () => AgentConfig[] {
	let agents: AgentConfig[] | undefined;
	const getAgents = () => {
		agents ??= discoverAgents();
		return agents;
	};

	registerAgentCatalogProvider(getAgents);
	return getAgents;
}
