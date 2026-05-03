/**
 * Process-scoped Basecamp session runtime state.
 *
 * Pi loads package extension entries with separate Jiti module caches. State
 * shared by core/workflow entries must live on globalThis rather than in a
 * module-local variable.
 */

import type { BasecampProjectState, SessionState } from "./config";

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

export function getProjectState(): BasecampProjectState | null {
	const state = getSessionState();
	if (!state) return null;
	return {
		projectName: state.projectName,
		project: state.project,
		additionalDirs: state.additionalDirs,
		workingStyle: state.workingStyle,
		contextContent: state.contextContent,
		projectWarnings: state.projectWarnings,
	};
}

export function requireProjectState(): BasecampProjectState {
	const state = getProjectState();
	if (!state)
		throw new Error("Basecamp project state is not initialized; session startup has not resolved project config");
	return state;
}

export function setSessionState(state: SessionState): void {
	getSessionRuntime().state = state;
}

export function requireSessionState(): SessionState {
	const state = getSessionState();
	if (!state) throw new Error("Basecamp session state is not initialized");
	return state;
}
