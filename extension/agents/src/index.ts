/**
 * Agents extension — agent tool, agent discovery, slash commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerAgentCommands } from "./commands";
import { discoverAgents } from "./discovery";
import { registerAgentTool } from "./tool";
import type { AgentConfig } from "./types";

export default function (pi: ExtensionAPI) {
	let agents: AgentConfig[] = [];
	let sessionName = "";

	// --- Agent discovery, session naming, status line ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents(ctx.cwd);

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

	// --- Register agent tool and slash commands ---
	registerAgentTool(
		pi,
		() => agents,
		() => sessionName,
	);
	registerAgentCommands(pi, () => agents);
}
