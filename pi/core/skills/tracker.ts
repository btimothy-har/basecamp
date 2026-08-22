/**
 * Shared skill invocation tracker.
 *
 * Records which skills the model has loaded via skill({ name }) during
 * the current session. Backed by a process-scoped singleton so `/reload`
 * preserves one shared tracker. Also owns the session lifecycle hooks that
 * reset the tracker on session start / compaction.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { processScoped } from "#core/global-registry.ts";

const getTrackerState = processScoped("basecamp.skillTracker", () => ({
	invokedSkills: new Set<string>(),
}));

export function resetInvokedSkills(): void {
	getTrackerState().invokedSkills.clear();
}

/**
 * Record a skill as invoked. Returns true if this is the first invocation
 * (caller may want to trigger a re-render or similar side-effect).
 */
export function trackSkillInvocation(name: string): boolean {
	const { invokedSkills } = getTrackerState();
	const sizeBefore = invokedSkills.size;
	invokedSkills.add(name);
	return invokedSkills.size !== sizeBefore;
}

/** Returns true if the named skill has been invoked this session. */
export function hasInvokedSkill(name: string): boolean {
	return getTrackerState().invokedSkills.has(name);
}

/** Returns invoked skills in invocation order for footer display. */
export function getInvokedSkills(): readonly string[] {
	return [...getTrackerState().invokedSkills];
}

/** Register lifecycle handlers to reset skill state on session events. */
export function registerSkillLifecycle(pi: ExtensionAPI): void {
	// /reload re-runs extension loading but leaves conversation context untouched, so
	// already-loaded skills stay in context and the tracker must survive it.
	pi.on("session_start", (event) => {
		if (event.reason === "reload") return;
		resetInvokedSkills();
	});

	pi.on("session_compact", () => {
		resetInvokedSkills();
	});

	// /skill:name is the user-facing invocation path: pi expands it into context
	// without the skill tool, so record it here or the reference gate would deny a
	// skill the user just loaded. Fires before expansion, on the raw text.
	pi.on("input", (event) => {
		const invoked = event.text.match(/^\/skill:([a-z0-9-]+)/i);
		if (invoked?.[1]) trackSkillInvocation(invoked[1]);
		return { action: "continue" } as const;
	});
}
