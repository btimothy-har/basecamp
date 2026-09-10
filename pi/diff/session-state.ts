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
	/** Retained across failed discovery and /reload so a retry can recover this launch. */
	beforeSessionIds?: string[];
}

interface OwnedReviews {
	byWorktree: Map<string, OwnedReview>;
}

const getOwnedReviews = processScoped<OwnedReviews>("basecamp.diffPanes", () => ({ byWorktree: new Map() }));

export function rememberPane(worktreeDir: string, paneId: string, before?: ReadonlySet<string>): void {
	getOwnedReviews().byWorktree.set(worktreeDir, { paneId, beforeSessionIds: before ? [...before] : undefined });
}

export function attachSession(worktreeDir: string, sessionId: string): void {
	const owned = getOwnedReviews().byWorktree.get(worktreeDir);
	if (owned) {
		owned.sessionId = sessionId;
		delete owned.beforeSessionIds;
	}
}

export function ownedReview(worktreeDir: string): OwnedReview | undefined {
	return getOwnedReviews().byWorktree.get(worktreeDir);
}

export function forgetPane(worktreeDir: string): void {
	getOwnedReviews().byWorktree.delete(worktreeDir);
}
