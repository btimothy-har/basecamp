export interface PaneGuardInput {
	tmux?: string;
	tmuxPane?: string;
	hasUI: boolean;
	agentDepth: number;
}

/** Create a pane only when interactive, inside tmux, and not a subagent. */
export function shouldCreatePane(input: PaneGuardInput): boolean {
	return Boolean(input.tmux) && Boolean(input.tmuxPane) && input.hasUI && input.agentDepth === 0;
}

/** Companion pane takes 65% of the width, leaving the pi pane at 35%. */
export const COMPANION_SPLIT_PERCENT = "65%";

export function buildSplitArgs(targetPane: string, cwd: string, command: string): string[] {
	return [
		"split-window",
		"-d",
		"-h",
		"-l",
		COMPANION_SPLIT_PERCENT,
		"-t",
		targetPane,
		"-c",
		cwd,
		"-P",
		"-F",
		"#{pane_id}",
		command,
	];
}

export function buildKillArgs(paneId: string): string[] {
	return ["kill-pane", "-t", paneId];
}

/** List every pane id across the tmux server, one per line. */
export function buildListPanesArgs(): string[] {
	return ["list-panes", "-a", "-F", "#{pane_id}"];
}

/** tmux pane ids look like "%5"; return the first such token or null. */
export function parsePaneId(stdout: string): string | null {
	const match = stdout
		.split("\n")
		.map((s) => s.trim())
		.find((s) => /^%\d+$/.test(s));
	return match ?? null;
}
