/**
 * Process-scoped Basecamp session runtime state.
 *
 * Pi loads package extension entries with separate Jiti module caches. State
 * shared by core/workflow entries must live on globalThis rather than in a
 * module-local variable.
 */

import type { SessionState } from "./config";

interface BasecampSessionRuntime {
	state: SessionState | null;
}

const sessionKey = Symbol.for("basecamp.session");

type GlobalWithBasecampSession = typeof globalThis & {
	[sessionKey]?: BasecampSessionRuntime;
};

function getSessionRuntime(): BasecampSessionRuntime {
	const globalObject = globalThis as GlobalWithBasecampSession;
	globalObject[sessionKey] ??= { state: null };
	return globalObject[sessionKey];
}

export function resetSessionRuntime(): void {
	getSessionRuntime().state = null;
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
