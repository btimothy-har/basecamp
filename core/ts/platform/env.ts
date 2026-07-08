/**
 * Environment contract for basecamp session state.
 *
 * Owns the BASECAMP_* env var schema, typed getters/setters, and the
 * companion-active flag. The workspace state hooks (registerWorkspaceStateProvider,
 * onWorkspaceStateChange) let pi-workspace override pi-core's git-detected defaults.
 *
 * Process-scoped via globalThis so `/reload` preserves state.
 */

// ---------------------------------------------------------------------------
// Companion active flag
// ---------------------------------------------------------------------------

const companionKey = Symbol.for("basecamp.companionActive");

type GlobalWithCompanion = typeof globalThis & {
	[companionKey]?: boolean;
};

/** Returns true if the companion dashboard is active in this session. */
export function isCompanionActive(): boolean {
	return (globalThis as GlobalWithCompanion)[companionKey] ?? false;
}

/** Set the companion-active flag. Called by pi-companion on register. */
export function setCompanionActive(active: boolean): void {
	(globalThis as GlobalWithCompanion)[companionKey] = active;
}

// ---------------------------------------------------------------------------
// BASECAMP_* env vars
// ---------------------------------------------------------------------------

export type BasecampEnvVar =
	| "BASECAMP_PROJECT"
	| "BASECAMP_REPO"
	| "BASECAMP_SCRATCH_DIR"
	| "BASECAMP_WORKTREE_DIR"
	| "BASECAMP_WORKTREE_LABEL"
	| "BASECAMP_AGENT_DEPTH"
	| "BASECAMP_AGENT_MAX_DEPTH"
	| "BASECAMP_SESSION_NAME"
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

// ---------------------------------------------------------------------------
// Workspace state hooks
// ---------------------------------------------------------------------------

import type { WorkspaceState } from "./workspace.ts";

type WorkspaceStateProvider = () => WorkspaceState | null;
type WorkspaceStateChangeListener = (state: WorkspaceState | null) => void;

interface WorkspaceHooksState {
	stateProvider: WorkspaceStateProvider | null;
	listeners: Set<WorkspaceStateChangeListener>;
}

const hooksKey = Symbol.for("basecamp.workspaceHooks");

type GlobalWithHooks = typeof globalThis & {
	[hooksKey]?: WorkspaceHooksState;
};

function getHooksState(): WorkspaceHooksState {
	const globalObject = globalThis as GlobalWithHooks;
	globalObject[hooksKey] ??= { stateProvider: null, listeners: new Set() };
	return globalObject[hooksKey];
}

/**
 * Register a provider that returns the current workspace state.
 * Pi-workspace calls this to override pi-core's default git-detected state.
 */
export function registerWorkspaceStateProvider(provider: WorkspaceStateProvider): void {
	getHooksState().stateProvider = provider;
}

/** Returns the workspace state from the registered provider, or null. */
export function getHookedWorkspaceState(): WorkspaceState | null {
	return getHooksState().stateProvider?.() ?? null;
}

/** Subscribe to workspace state changes. Returns an unsubscribe function. */
export function onWorkspaceStateChange(listener: WorkspaceStateChangeListener): () => void {
	const state = getHooksState();
	state.listeners.add(listener);
	return () => state.listeners.delete(listener);
}

/** Notify all listeners of a workspace state change. */
export function notifyWorkspaceStateChange(state: WorkspaceState | null): void {
	for (const listener of getHooksState().listeners) {
		listener(state);
	}
}
