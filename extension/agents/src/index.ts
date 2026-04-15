/**
 * Agents extension — worker tool, agent discovery, slash commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { getState } from "../../core/src/session";
import { discoverAgents } from "./discovery";
import { registerWorkerTool, setStatusIdle } from "./tool";
import { registerAgentCommands } from "./commands";
import { closeWorker } from "./worker-index";
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
			ctx.ui.notify(
				`basecamp: ${agents.length} agent(s) discovered`,
				"info",
			);
		}
	});

	// --- Register worker tool and slash commands ---
	registerWorkerTool(
		pi,
		() => agents,
		() => sessionName,
	);
	registerAgentCommands(pi, () => agents);

	// --- Worker cleanup on session shutdown ---
	pi.on("session_shutdown", async () => {
		const workerName = process.env.BASECAMP_WORKER_NAME;
		if (workerName) closeWorker(workerName);
	});
}
