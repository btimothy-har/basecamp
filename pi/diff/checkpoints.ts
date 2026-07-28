/**
 * User-initiated review checkpoints, keyed by review worktree.
 *
 * Checkpoints mark where the user's last `/diff` review ended: `/diff` records
 * one, `/diff last` anchors its diff to it, and `annotate_changeset` stamps it
 * on the sidecar it writes. Surviving state, not wiring: like basecamp.diffTabs
 * a checkpoint outlives the pi session that recorded it. Deliberately in-memory
 * only — a checkpoint older than the process is useless because the hunk
 * sessions behind those reviews die with the process too.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { gitOutput } from "#core/git/repo.ts";
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
 * Returns the surviving checkpoint, or undefined.
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

/**
 * The SHA to anchor annotations to: the recorded checkpoint's last, or HEAD
 * when none was recorded — under the clean-tree assumption HEAD IS the last
 * diff point, so the store self-initializes without extra bookkeeping.
 */
export async function lastCheckpointOrHead(pi: ExtensionAPI, worktreeDir: string): Promise<string> {
	return getCheckpoint(worktreeDir)?.last ?? (await gitOutput(pi, worktreeDir, ["rev-parse", "HEAD"]));
}
