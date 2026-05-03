/**
 * Process-scoped Basecamp project runtime state.
 *
 * Pi loads package extension entries with separate Jiti module caches. State
 * shared by core/workflow entries must live on globalThis rather than in a
 * module-local variable.
 */

import type { BasecampProjectState } from "./config";

interface BasecampProjectRuntime {
	state: BasecampProjectState | null;
}

const projectKey = Symbol.for("basecamp.project");

type GlobalWithBasecampProject = typeof globalThis & {
	[projectKey]?: BasecampProjectRuntime;
};

function getProjectRuntime(): BasecampProjectRuntime {
	const globalObject = globalThis as GlobalWithBasecampProject;
	globalObject[projectKey] ??= { state: null };
	return globalObject[projectKey];
}

export function resetBasecampProjectRuntime(): void {
	getProjectRuntime().state = null;
}

export function getBasecampProjectState(): BasecampProjectState | null {
	return getProjectRuntime().state;
}

export function requireBasecampProjectState(): BasecampProjectState {
	const state = getBasecampProjectState();
	if (!state)
		throw new Error("Basecamp project state is not initialized; session startup has not resolved project config");
	return state;
}

export function setBasecampProjectState(state: BasecampProjectState): void {
	getProjectRuntime().state = state;
}
