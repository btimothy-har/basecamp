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

/** Prints "hello world" then blocks so the pane stays alive. Single string => tmux runs it via sh. */
export const PANE_COMMAND = "printf 'hello world\\n'; exec tail -f /dev/null";

export function buildSplitArgs(targetPane: string, command: string): string[] {
	return ["split-window", "-d", "-h", "-t", targetPane, "-P", "-F", "#{pane_id}", command];
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
