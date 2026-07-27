/**
 * Hunk reviews `/diff` has opened, keyed by worktree.
 *
 * Surviving state, not wiring: the tab and the hunk session behind it outlive
 * the pi session that opened them, and losing their ids on /reload would
 * strand a window nothing can close and notes nothing can read.
 */

import { processScoped } from "#core/global-registry.ts";

export interface OwnedReview {
	tabId: string;
	/** Absent until hunk registers with its daemon, which can fail. */
	sessionId?: string;
}

interface OwnedReviews {
	byWorktree: Map<string, OwnedReview>;
}

const getOwnedReviews = processScoped<OwnedReviews>("basecamp.diffTabs", () => ({ byWorktree: new Map() }));

export function rememberTab(worktreeDir: string, tabId: string): void {
	getOwnedReviews().byWorktree.set(worktreeDir, { tabId });
}

export function attachSession(worktreeDir: string, sessionId: string): void {
	const owned = getOwnedReviews().byWorktree.get(worktreeDir);
	if (owned) owned.sessionId = sessionId;
}

export function ownedReview(worktreeDir: string): OwnedReview | undefined {
	return getOwnedReviews().byWorktree.get(worktreeDir);
}

export function forgetTab(worktreeDir: string): void {
	getOwnedReviews().byWorktree.delete(worktreeDir);
}
