/**
 * Catalog provider for workflow-owned agents.
 */

import type { CatalogItem, CatalogProvider } from "../dependencies.ts";
import type { AgentConfig } from "./discovery.ts";
import { DEFAULT_AGENT_MAX_DEPTH, getAgentToolAllowlist } from "./types.ts";

function agentsAvailable(): boolean {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	return depth < maxDepth;
}

function toCatalogItem(agent: AgentConfig): CatalogItem {
	return {
		type: "agents",
		name: agent.name,
		description: agent.description,
		path: agent.filePath,
		meta: {
			source: agent.source,
			model: agent.model,
			tools: getAgentToolAllowlist(agent).join(", "),
			...(agent.skills ? { skills: agent.skills.join(", ") } : {}),
		},
	};
}

export function registerAgentCatalogProvider(
	getAgents: () => AgentConfig[],
	deps: { registerCatalogProvider: (provider: CatalogProvider) => void },
): void {
	deps.registerCatalogProvider({
		id: "basecamp.agents",
		list: () => {
			if (!agentsAvailable()) return [];
			return getAgents().map(toCatalogItem);
		},
	});
}
