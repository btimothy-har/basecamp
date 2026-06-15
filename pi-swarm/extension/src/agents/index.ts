/**
 * Agent workflow registration — agent tool, discovery, and slash commands.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PiSwarmDependencies } from "../dependencies.ts";
import { registerAgentCatalogProvider } from "./catalog.ts";
import { registerAgentCommands } from "./commands.ts";
import { discoverAgents } from "./discovery.ts";
import { registerAgentTool } from "./tool.ts";
import type { AgentConfig } from "./types.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "./types.ts";

export function registerAgents(pi: ExtensionAPI, deps: PiSwarmDependencies): void {
	let agents: AgentConfig[] = [];
	let sessionName = "";

	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;

	// --- Agent discovery and session naming ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents();
		registerAgentCatalogProvider(agents, { registerCatalogProvider: deps.registerCatalogProvider });

		sessionName = pi.getSessionName()?.trim() || "";
		if (!sessionName) {
			sessionName = ctx.sessionManager.getSessionId().replace(/-/g, "").slice(-8);
			pi.setSessionName(sessionName);
		}
		process.env.BASECAMP_SESSION_NAME = sessionName;

		if (agents.length > 0) {
			ctx.ui.notify(`basecamp: ${agents.length} agent(s) discovered`, "info");
		}
	});

	// --- Register tools and slash commands (skip at max depth) ---
	if (!atMaxDepth) {
		registerAgentTool(
			pi,
			() => agents,
			() => sessionName,
			deps,
		);
		registerAgentCommands(pi, () => agents);
	}
}
