/** Environment contract for basecamp session state. */

export type BasecampEnvVar =
	| "BASECAMP_PROJECT"
	| "BASECAMP_REPO"
	| "BASECAMP_SCRATCH_DIR"
	| "BASECAMP_WORKTREE_DIR"
	| "BASECAMP_WORKTREE_LABEL"
	| "BASECAMP_WORKTREES_ROOT"
	| "BASECAMP_AGENT_DEPTH"
	| "BASECAMP_AGENT_MAX_DEPTH"
	| "BASECAMP_EXTERNAL_SANDBOX"
	| "BASECAMP_SESSION_NAME"
	| "BASECAMP_USER_FACING"
	| "BASECAMP_BROWSER_PATH";

/** Typed getter for a BASECAMP_* env var. Returns undefined if not set. */
export function getBasecampEnv(name: BasecampEnvVar): string | undefined {
	const value = process.env[name];
	return value === "" ? undefined : value;
}

/** Typed setter for a BASECAMP_* env var. Empty string clears it. */
export function setBasecampEnv(name: BasecampEnvVar, value: string): void {
	process.env[name] = value;
}

/** Returns the current agent depth (0 for primary sessions, >0 for subagents). */
export function getAgentDepth(): number {
	return Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
}

/** Returns true if this is a subagent session. */
export function isSubagent(): boolean {
	return getAgentDepth() > 0;
}
