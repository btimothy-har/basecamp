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

function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

export function buildCompanionCommand(snapshotPath: string, cwd: string, scratchDir?: string): string {
	const base = `basecamp companion dashboard --snapshot ${shellQuote(snapshotPath)} --cwd ${shellQuote(cwd)}`;
	return scratchDir ? `${base} --scratch ${shellQuote(scratchDir)}` : base;
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

/** tmux pane ids look like "%5"; return the first such token or null. */
export function parsePaneId(stdout: string): string | null {
	const match = stdout
		.split("\n")
		.map((s) => s.trim())
		.find((s) => /^%\d+$/.test(s));
	return match ?? null;
}
