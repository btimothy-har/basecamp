/**
 * Catalog provider for workflow-owned agents.
 */

import { type CatalogItem, registerCatalogProvider } from "../../../platform/catalog";
import type { AgentConfig } from "./discovery.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "./types";

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
			...(agent.tools ? { tools: agent.tools.join(", ") } : {}),
			...(agent.skills ? { skills: agent.skills.join(", ") } : {}),
		},
	};
}

export function registerAgentCatalogProvider(agents: AgentConfig[]): void {
	registerCatalogProvider({
		id: "basecamp.agents",
		list: () => {
			if (!agentsAvailable()) return [];
			return agents.map(toCatalogItem);
		},
	});
}
