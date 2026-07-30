/**
 * Process-scoped pause state for the bash reviewer.
 *
 * The pause is the runtime escape hatch: `/bash-guard off` skips the LLM gate
 * entirely — the fast path (`isTriviallySafe`) still runs, so a trivially-safe
 * command is never sent to the model regardless. It is a **deliberately
 * temporary** session toggle, not a security control: the env+flag triad in
 * `index.ts` remains the only durable opt-out.
 *
 * The state is backed by a `process.env` var (`BASECAMP_BASH_REVIEWER_PAUSED`)
 * rather than only a `processScoped` global. Subagents are separate processes —
 * `globalThis` does not cross that boundary — but `buildAgentEnv` copies every
 * `BASECAMP_*` var into the child env, and this var is not in
 * `RESTRICTED_AGENT_SPAWN_ENV_VARS`, so the pause propagates to subagent
 * spawns. `loadDotenv` refuses all `BASECAMP_*` keys from a repo `.env`, so a
 * repo `.env` cannot forge the pause state.
 *
 * The listener set uses `processScoped` so the footer re-renders on a pause
 * toggle even after `/reload`.
 */

import { processScoped } from "#core/global-registry.ts";
import { getBasecampEnv, setBasecampEnv } from "#core/host/env.ts";

type PauseListener = (paused: boolean) => void;

interface ReviewerPauseState {
	listeners: Set<PauseListener>;
	/** The active session's unsubscribe, stored so a `/reload` can clear it before re-subscribing. */
	currentUnsubscribe: (() => void) | null;
}

const getReviewerPauseState = processScoped<ReviewerPauseState>("basecamp.bashReviewer.pause", () => ({
	listeners: new Set(),
	currentUnsubscribe: null,
}));

export function isReviewerPaused(): boolean {
	return getBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED") === "1";
}

export function setReviewerPaused(next: boolean): boolean {
	const current = isReviewerPaused();
	if (current === next) return current;

	if (next) setBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED", "1");
	else setBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED", "");

	for (const listener of getReviewerPauseState().listeners) {
		listener(next);
	}
	return next;
}

/**
 * Register a pause-change listener, replacing any previous one.
 *
 * The listener set is `processScoped` (survives `/reload`), but the
 * `unsubscribe` closure from the previous module load is unreachable after a
 * reload — `session_start` fires again without an intervening
 * `session_shutdown`. This mirrors the hub's `clearHubMetadataWiring` pattern:
 * store the unsubscribe in the same surviving state and call it before
 * registering a new listener, so stale-`ctx` callbacks don't accumulate.
 */
export function onReviewerPauseChange(listener: PauseListener): () => void {
	const state = getReviewerPauseState();
	state.currentUnsubscribe?.();
	state.listeners.add(listener);
	const unsubscribe = () => {
		state.listeners.delete(listener);
		if (state.currentUnsubscribe === unsubscribe) state.currentUnsubscribe = null;
	};
	state.currentUnsubscribe = unsubscribe;
	return unsubscribe;
}
