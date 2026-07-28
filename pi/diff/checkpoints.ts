/**
 * User-initiated review checkpoints, keyed by review worktree.
 *
 * Checkpoints mark where the user's last `/diff` review ended: `/diff` records
 * one and `/diff last` anchors its diff to it. They are review *targets* only —
 * agent annotations are anchored to the review base instead, because that
 * identifies the span they describe. Surviving state, not wiring: like
 * basecamp.diffPanes a checkpoint outlives the pi session that recorded it.
 * Deliberately in-memory only — a checkpoint older than the process is useless
 * because the hunk sessions behind those reviews die with the process too.
 */

import { processScoped } from "#core/global-registry.ts";

export interface Checkpoint {
	/** Merge-base recorded with the checkpoint; invalidates when the branch/base moves. */
	base: string;
	/** HEAD SHA at the moment the checkpoint was taken. */
	last: string;
}

interface Checkpoints {
	byWorktree: Map<string, Checkpoint>;
}

const getCheckpoints = processScoped<Checkpoints>("basecamp.diffCheckpoints", () => ({ byWorktree: new Map() }));

/** The recorded checkpoint for a worktree, or undefined. */
export function getCheckpoint(worktreeDir: string): Checkpoint | undefined {
	return getCheckpoints().byWorktree.get(worktreeDir);
}

/** Record (or overwrite) the checkpoint for a worktree. */
export function recordCheckpoint(worktreeDir: string, checkpoint: Checkpoint): void {
	getCheckpoints().byWorktree.set(worktreeDir, checkpoint);
}

/** Drop the checkpoint, e.g. after invalidation. */
export function forgetCheckpoint(worktreeDir: string): void {
	getCheckpoints().byWorktree.delete(worktreeDir);
}

/**
 * Drop the checkpoint when the base it was recorded against no longer matches
 * the worktree's current merge-base (worktree dirs are reused across branches).
 * Returns the surviving checkpoint, or undefined. Base equality is necessary
 * but not sufficient — sibling branches share a merge-base — so callers that
 * diff against `last` must also confirm it is an ancestor of HEAD.
 */
export function validateCheckpoint(worktreeDir: string, currentBase: string): Checkpoint | undefined {
	const checkpoint = getCheckpoint(worktreeDir);
	if (checkpoint === undefined) return undefined;
	if (checkpoint.base !== currentBase) {
		forgetCheckpoint(worktreeDir);
		return undefined;
	}
	return checkpoint;
}
