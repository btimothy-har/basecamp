/**
 * Basecamp extension for pi.
 *
 * Provides:
 *   - Project-aware session lifecycle (--project, --label, --style flags)
 *   - System prompt assembly (env block, working style, system.md, context)
 *   - Worktree creation and tool-level enforcement
 *   - Git protection (force push, remote ref deletion, destructive gh commands)
 *   - Observer integration (transcript ingestion for semantic recall)
 *   - Session handoff (/handoff command)
 *   - Skill nudges (contextual skill suggestions)
 *   - Agent system (worker tool, discovery, pane/background spawning)
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerSession, getState } from "./core/session";
import { registerPrompt } from "./core/prompt";
import { registerGitProtect } from "./git-protect";
import { registerNudges } from "./core/nudges";
import { registerHandoff } from "./core/handoff";
import { registerOpenCommand } from "./core/open";
import { discoverAgents } from "./agents/discovery";
import { registerWorkerTool } from "./agents/tool";
import { registerAgentCommands } from "./agents/commands";
import { closeWorker } from "./agents/worker-index";
import type { AgentConfig } from "./agents/types";

export default function (pi: ExtensionAPI) {
	let agents: AgentConfig[] = [];
	let sessionName = "";

	// --- Core modules ---
	registerSession(pi);
	registerPrompt(pi);
	registerGitProtect(pi);
	registerNudges(pi);
	registerHandoff(pi);
	registerOpenCommand(pi, getState);

	// --- Agent discovery and session naming ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents(ctx.cwd);

		// Build session name from project if available
		const state = getState();
		sessionName = pi.getSessionName()?.trim() || "";
		if (!sessionName) {
			const project = state.projectName || "session";
			const id = ctx.sessionManager.getSessionId().slice(0, 8);
			sessionName = `bc-${project}-${id}`;
			pi.setSessionName(sessionName);
		}
		process.env.BASECAMP_SESSION_NAME = sessionName;

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
