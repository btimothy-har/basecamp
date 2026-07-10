/** The live per-process session-state cell and its accessors. */

import type { ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { processScoped } from "../../global-registry.ts";
import { loadForkInheritedFields, resolveParentSessionFile } from "./fork.ts";
import type {
	BasecampSessionState,
	SessionStateIdentity,
	SessionStateUpdater,
	SessionTitleChangeListener,
} from "./model.ts";
import { createDefaultSessionState, loadSessionState, saveSessionState } from "./persistence.ts";

// Surviving session state: /reload re-imports the extension with fresh module
// instances, so the live session snapshot lives behind a process-scoped key.
interface SessionStateRuntime {
	current: BasecampSessionState | null;
	stateDir: string | undefined;
	titleListeners: Set<SessionTitleChangeListener>;
}

const getSessionStateRuntimeScoped = processScoped<SessionStateRuntime>("basecamp.sessionState", () => ({
	current: null,
	stateDir: undefined,
	titleListeners: new Set(),
}));

function getSessionStateRuntime(): SessionStateRuntime {
	return getSessionStateRuntimeScoped();
}

function sessionIdentityFromContext(ctx: ExtensionContext): SessionStateIdentity {
	return {
		sessionId: ctx.sessionManager.getSessionId(),
		sessionFile: ctx.sessionManager.getSessionFile() ?? null,
	};
}

export function initializeCurrentSessionState(ctx: ExtensionContext, stateDir?: string): BasecampSessionState {
	const runtime = getSessionStateRuntime();
	runtime.stateDir = stateDir;
	runtime.current = loadSessionState(sessionIdentityFromContext(ctx), stateDir);
	return runtime.current;
}

export function initializeCurrentSessionStateForEvent(
	event: SessionStartEvent,
	ctx: ExtensionContext,
	stateDir?: string,
): BasecampSessionState {
	if (event.reason !== "fork") return initializeCurrentSessionState(ctx, stateDir);

	const runtime = getSessionStateRuntime();
	runtime.stateDir = stateDir;
	const childState = createDefaultSessionState(sessionIdentityFromContext(ctx));
	const parentSessionFile = resolveParentSessionFile(event, ctx);
	const inheritedFields = parentSessionFile ? loadForkInheritedFields(parentSessionFile, stateDir) : null;
	runtime.current = saveSessionState({ ...childState, ...inheritedFields }, stateDir);
	return runtime.current;
}

/**
 * Initialize session state for `event` if it is not already initialized for the
 * current session, otherwise return the existing state. This makes consumers
 * that read session state during their own `session_start` handler independent
 * of cross-extension handler ordering: whichever handler runs first performs
 * the (identical, event-aware) initialization, and later callers reuse it.
 */
export function ensureCurrentSessionStateForEvent(
	event: SessionStartEvent,
	ctx: ExtensionContext,
	stateDir?: string,
): BasecampSessionState {
	const { current } = getSessionStateRuntime();
	const identity = sessionIdentityFromContext(ctx);
	if (
		current &&
		current.sessionId === identity.sessionId &&
		(current.sessionFile ?? null) === (identity.sessionFile ?? null)
	) {
		return current;
	}
	return initializeCurrentSessionStateForEvent(event, ctx, stateDir);
}

export function getCurrentSessionState(): Readonly<BasecampSessionState> {
	const { current } = getSessionStateRuntime();
	if (!current) throw new Error("Basecamp session state is not initialized.");
	return current;
}

export function getCurrentSessionStateIfInitialized(): Readonly<BasecampSessionState> | null {
	return getSessionStateRuntime().current;
}

function notifyTitleChange(state: BasecampSessionState): void {
	for (const listener of getSessionStateRuntime().titleListeners) {
		try {
			listener(state.title, state);
		} catch {
			// best effort
		}
	}
}

export function onCurrentSessionTitleChange(listener: SessionTitleChangeListener): () => void {
	const runtime = getSessionStateRuntime();
	runtime.titleListeners.add(listener);
	return () => {
		runtime.titleListeners.delete(listener);
	};
}

export function updateCurrentSessionState(updater: SessionStateUpdater): BasecampSessionState {
	const runtime = getSessionStateRuntime();
	const existing = getCurrentSessionState();
	const previousTitle = existing.title;
	const patch = typeof updater === "function" ? updater(existing) : updater;
	runtime.current = saveSessionState({ ...existing, ...patch }, runtime.stateDir);
	if (runtime.current.title !== previousTitle) notifyTitleChange(runtime.current);
	return runtime.current;
}

export function updateCurrentSessionStateIfInitialized(updater: SessionStateUpdater): BasecampSessionState | null {
	if (!getSessionStateRuntime().current) return null;
	return updateCurrentSessionState(updater);
}

export function resetCurrentSessionState(): void {
	const runtime = getSessionStateRuntime();
	runtime.current = null;
	runtime.stateDir = undefined;
}
