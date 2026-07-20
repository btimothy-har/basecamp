/**
 * Catalog provider for workflow-owned agents.
 */

import { type CatalogItem, registerCatalogProvider } from "../../catalog/index.ts";
import { getAgentDepth } from "../../host/env.ts";
import type { AgentConfig } from "./discovery.ts";
import { DEFAULT_AGENT_MAX_DEPTH, getAgentToolAllowlist } from "./types.ts";

function agentsAvailable(): boolean {
	const depth = getAgentDepth();
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
			tools: getAgentToolAllowlist().join(", "),
		},
	};
}

export function registerAgentCatalogProvider(getAgents: () => AgentConfig[]): void {
	registerCatalogProvider({
		id: "basecamp.agents",
		list: () => {
			if (!agentsAvailable()) return [];
			return getAgents().map(toCatalogItem);
		},
	});
}
