/**
 * Agent catalog registration.
 */

import type { PiSwarmDependencies } from "../dependencies.ts";
import { registerAgentCatalogProvider } from "./catalog.ts";
import { discoverAgents } from "./discovery.ts";
import type { AgentConfig } from "./types.ts";

export function registerAgentCatalog(deps: Pick<PiSwarmDependencies, "registerCatalogProvider">): () => AgentConfig[] {
	let agents: AgentConfig[] | undefined;
	const getAgents = () => {
		agents ??= discoverAgents();
		return agents;
	};

	registerAgentCatalogProvider(getAgents, { registerCatalogProvider: deps.registerCatalogProvider });
	return getAgents;
}
