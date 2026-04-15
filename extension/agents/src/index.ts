/**
 * Agents extension — agent tool, agent discovery, slash commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { getState } from "../../core/src/session";
import { registerAgentCommands } from "./commands";
import { discoverAgents } from "./discovery";
import { registerAgentTool, setStatusIdle } from "./tool";
import type { AgentConfig } from "./types";

export default function (pi: ExtensionAPI) {
	let agents: AgentConfig[] = [];
	let sessionName = "";

	// --- Agent discovery, session naming, status line ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents(ctx.cwd);

		const state = getState();
		sessionName = pi.getSessionName()?.trim() || "";
		if (!sessionName) {
			const project = state.projectName || "session";
			const id = ctx.sessionManager.getSessionId().slice(0, 8);
			sessionName = `bc-${project}-${id}`;
			pi.setSessionName(sessionName);
		}
		process.env.BASECAMP_SESSION_NAME = sessionName;

		// Status line: idle with agent count
		setStatusIdle(ctx, agents.length);

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
