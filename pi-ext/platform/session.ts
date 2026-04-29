/**
 * Process-scoped Basecamp session runtime state.
 *
 * Pi loads package extension entries with separate Jiti module caches. State
 * shared by core/workflow entries must live on globalThis rather than in a
 * module-local variable.
 */

import type { SessionState } from "./config";
import type { GitStatus } from "./context";

interface BasecampSessionRuntime {
	state: SessionState | null;
	gitStatus: GitStatus | null;
}

const sessionKey = Symbol.for("basecamp.session");

type GlobalWithBasecampSession = typeof globalThis & {
	[sessionKey]?: BasecampSessionRuntime;
};

function getSessionRuntime(): BasecampSessionRuntime {
	const globalObject = globalThis as GlobalWithBasecampSession;
	globalObject[sessionKey] ??= { state: null, gitStatus: null };
	return globalObject[sessionKey];
}

export function resetSessionRuntime(): void {
	const runtime = getSessionRuntime();
	runtime.state = null;
	runtime.gitStatus = null;
}

export function getSessionState(): SessionState | null {
	return getSessionRuntime().state;
}

export function setSessionState(state: SessionState): void {
	getSessionRuntime().state = state;
}

export function requireSessionState(): SessionState {
	const state = getSessionState();
	if (!state) throw new Error("Basecamp session state is not initialized");
	return state;
}

export function getSessionGitStatus(): GitStatus | null {
	return getSessionRuntime().gitStatus;
}

export function setSessionGitStatus(gitStatus: GitStatus | null): void {
	getSessionRuntime().gitStatus = gitStatus;
}
