/**
 * Agent workflow registration — agent tool, discovery, slash commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerAgentCatalogProvider } from "./catalog";
import { registerAgentCommands } from "./commands";
import { discoverAgents } from "./discovery";
import { registerAgentTool } from "./tool";
import { type AgentConfig, DEFAULT_AGENT_MAX_DEPTH } from "./types";

export function registerAgents(pi: ExtensionAPI) {
	let agents: AgentConfig[] = [];
	let sessionName = "";

	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;

	// --- Agent discovery, session naming, status line ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents(ctx.cwd);
		registerAgentCatalogProvider(agents);

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

	// --- Register agent tool and slash commands (skip at max depth) ---
	if (!atMaxDepth) {
		registerAgentTool(
			pi,
			() => agents,
			() => sessionName,
		);
		registerAgentCommands(pi, () => agents);
	}
}
