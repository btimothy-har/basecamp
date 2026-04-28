/**
 * Agent workflow registration — agent tool, discovery, slash commands, async lifecycle.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { registerAsyncNotify } from "./async-notify";
import { registerAgentStatusTool } from "./async-status-tool";
import {
	type AsyncWatcherState,
	createWatcherState,
	getActiveJobs,
	killAllAsyncAgents,
	resetAsyncWatcher,
	startAsyncWatcher,
	stopAsyncWatcher,
} from "./async-watcher";
import { registerAgentCatalogProvider } from "./catalog";
import { registerAgentCommands } from "./commands";
import { discoverAgents } from "./discovery";
import { registerAgentTool } from "./tool";
import { type AgentConfig, DEFAULT_AGENT_MAX_DEPTH } from "./types";

const ASYNC_STATUS_KEY = "basecamp-async-agents";

function updateAsyncStatusLine(
	watcherState: AsyncWatcherState,
	setStatus: (key: string, text: string | undefined) => void,
): void {
	const active = getActiveJobs(watcherState);
	if (active.length === 0) {
		setStatus(ASYNC_STATUS_KEY, undefined);
		return;
	}
	const names = active.map((j) => j.agent).join(", ");
	setStatus(ASYNC_STATUS_KEY, `⏳ ${active.length} background: ${names}`);
}

export function registerAgents(pi: ExtensionAPI) {
	let agents: AgentConfig[] = [];
	let sessionName = "";
	const watcherState = createWatcherState();

	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;

	// --- Agent discovery, session naming, async lifecycle ---
	pi.on("session_start", async (_event, ctx) => {
		agents = discoverAgents();
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

		// Wire status line updates and (re)start async watcher
		watcherState.onUpdate = () => {
			if (ctx.hasUI) updateAsyncStatusLine(watcherState, ctx.ui.setStatus.bind(ctx.ui));
		};
		resetAsyncWatcher(watcherState);
		startAsyncWatcher(watcherState, pi.events);
	});

	pi.on("session_shutdown", async () => {
		killAllAsyncAgents(watcherState);
		stopAsyncWatcher(watcherState);
	});

	// --- Register tools and slash commands (skip at max depth) ---
	if (!atMaxDepth) {
		registerAgentTool(
			pi,
			() => agents,
			() => sessionName,
		);
		registerAgentCommands(pi, () => agents);
		registerAgentStatusTool(pi, watcherState);
		registerAsyncNotify(pi);
	}
}
