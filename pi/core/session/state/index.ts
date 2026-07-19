/**
 * Session state — the stable import surface (`#core/session/state/index.ts`).
 * Model/schema in model.ts, file persistence in persistence.ts, fork
 * inheritance in fork.ts, the live process-scoped cell in current.ts.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { ensureCurrentSessionStateForEvent, resetCurrentSessionState } from "./current.ts";

export {
	ensureCurrentSessionStateForEvent,
	getCurrentSessionState,
	getCurrentSessionStateIfInitialized,
	initializeCurrentSessionState,
	initializeCurrentSessionStateForEvent,
	onCurrentSessionTitleChange,
	resetCurrentSessionState,
	updateCurrentSessionState,
	updateCurrentSessionStateIfInitialized,
} from "./current.ts";
export type {
	BasecampSessionState,
	SessionStateActiveWorktree,
	SessionStateAgentMode,
	SessionStateIdentity,
	SessionStatePatch,
	SessionStateUpdater,
	SessionStateWorktree,
	SessionTitleChangeListener,
} from "./model.ts";
export { SESSION_STATE_AGENT_MODES } from "./model.ts";
export { buildSessionStatePath, createDefaultSessionState, loadSessionState, saveSessionState } from "./persistence.ts";

export function registerState(pi: ExtensionAPI): void {
	pi.on("session_start", async (event, ctx) => {
		ensureCurrentSessionStateForEvent(event, ctx);
	});

	pi.on("session_shutdown", async () => {
		resetCurrentSessionState();
	});
}

export default registerState;
