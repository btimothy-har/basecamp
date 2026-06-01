import type { ExtensionAPI, SessionShutdownEvent } from "@earendil-works/pi-coding-agent";
import { exec } from "../platform/exec.ts";
import { getPaneState } from "./state.ts";
import { buildKillArgs, buildSplitArgs, PANE_COMMAND, parsePaneId, shouldCreatePane } from "./tmux.ts";

const PANES_WARNING_PREFIX = "panes:";

export default function registerPanes(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		const state = getPaneState();
		if (state.paneId) return;

		const targetPane = process.env.TMUX_PANE;
		const shouldCreate = shouldCreatePane({
			tmux: process.env.TMUX,
			tmuxPane: targetPane,
			hasUI: ctx.hasUI,
			agentDepth: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0"),
		});
		if (!shouldCreate) return;

		try {
			const result = await exec(pi, "tmux", buildSplitArgs(targetPane as string, PANE_COMMAND));
			state.paneId = parsePaneId(result.stdout);
		} catch (err) {
			const message = err instanceof Error ? err.message : String(err);
			ctx.ui.notify(`${PANES_WARNING_PREFIX} failed to open pane — ${message}`, "warning");
		}
	});

	pi.on("session_shutdown", async (event: SessionShutdownEvent) => {
		if (event.reason !== "quit") return;

		const state = getPaneState();
		if (!state.paneId) return;

		try {
			await exec(pi, "tmux", buildKillArgs(state.paneId));
		} catch {
			// best effort
		}

		state.paneId = null;
	});
}
