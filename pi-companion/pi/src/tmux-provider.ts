import { exec } from "pi-core/platform/exec.ts";
import type { PaneProvider } from "./pane-provider.ts";
import { buildKillArgs, buildListPanesArgs, buildSplitArgs, parsePaneId, shouldCreatePane } from "./tmux.ts";

export interface TmuxPaneProviderInput {
	tmux?: string;
	tmuxPane?: string;
	hasUI: boolean;
	agentDepth: number;
}

function createTmuxProvider(targetPane: string | null): PaneProvider {
	return {
		name: "tmux",
		async createPane(pi, createInput) {
			if (!targetPane) throw new Error("missing tmux target pane");
			const result = await exec(pi, "tmux", buildSplitArgs(targetPane, createInput.cwd, createInput.command));
			return parsePaneId(result.stdout);
		},
		async paneStillExists(pi, paneId) {
			try {
				const result = await exec(pi, "tmux", buildListPanesArgs());
				if (result.code !== 0) return true;
				const ids = result.stdout
					.split("\n")
					.map((line) => line.trim())
					.filter(Boolean);
				return ids.includes(paneId);
			} catch {
				return true;
			}
		},
		async closePane(pi, paneId) {
			await exec(pi, "tmux", buildKillArgs(paneId));
		},
	};
}

export function createTmuxPaneProvider(input: TmuxPaneProviderInput): PaneProvider | null {
	if (!shouldCreatePane(input) || !input.tmuxPane) return null;
	return createTmuxProvider(input.tmuxPane);
}

export function createTmuxPaneCloser(): PaneProvider {
	return createTmuxProvider(null);
}
