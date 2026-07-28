/**
 * Hunk reviews `/diff` has opened, keyed by worktree.
 *
 * Surviving state, not wiring: the pane and the hunk session behind it outlive
 * the pi session that opened them, and losing their ids on /reload would
 * strand a pane nothing can close and notes nothing can read.
 */

import { processScoped } from "#core/global-registry.ts";

export interface OwnedReview {
	paneId: string;
	/** Absent until hunk registers with its daemon, which can fail. */
	sessionId?: string;
}

interface OwnedReviews {
	byWorktree: Map<string, OwnedReview>;
}

const getOwnedReviews = processScoped<OwnedReviews>("basecamp.diffPanes", () => ({ byWorktree: new Map() }));

export function rememberPane(worktreeDir: string, paneId: string): void {
	getOwnedReviews().byWorktree.set(worktreeDir, { paneId });
}

export function attachSession(worktreeDir: string, sessionId: string): void {
	const owned = getOwnedReviews().byWorktree.get(worktreeDir);
	if (owned) owned.sessionId = sessionId;
}

export function ownedReview(worktreeDir: string): OwnedReview | undefined {
	return getOwnedReviews().byWorktree.get(worktreeDir);
}

export function forgetPane(worktreeDir: string): void {
	getOwnedReviews().byWorktree.delete(worktreeDir);
}

/** Drops a dead session while keeping a pane id that still needs closing. */
export function forgetSession(worktreeDir: string): void {
	const owned = getOwnedReviews().byWorktree.get(worktreeDir);
	if (owned) delete owned.sessionId;
}
