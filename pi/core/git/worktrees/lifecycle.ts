/**
 * Worktree lifecycle primitives for dispatched mutative agents.
 *
 * Pure git verbs (create-from-ref, lock, unlock, remove) with no session state — the
 * confinement guard and the dispatch orchestration that use these live elsewhere
 * (docs/design/agent-isolation.md). `createAgentWorktree` branches an agent's own worktree
 * from the parent's HEAD and locks it; the parent later integrates the branch by merge and
 * tears the worktree down.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "../constants.ts";
import {
	ensureWorktreeLabel,
	findWorktreeRecord,
	gitWorktreeRecords,
	validateNoSymlinkedWorktreePath,
	type WorktreeResult,
} from "./crud.ts";

const GIT_TIMEOUT_MS = 30_000;
const LOCK_TIMEOUT_MS = 15_000;

/** Lock a worktree so cleanup/migration cannot yank it mid-run. Idempotent. */
export async function lockWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	reason?: string,
): Promise<void> {
	const args = ["-C", repoRoot, "worktree", "lock", ...(reason ? ["--reason", reason] : []), worktreeDir];
	const result = await pi.exec("git", args, { timeout: LOCK_TIMEOUT_MS });
	if (result.code !== 0 && !/already locked/i.test(result.stderr)) {
		throw new Error(`Failed to lock worktree: ${result.stderr}`);
	}
}

/** Unlock a worktree. Idempotent — a not-locked worktree is a no-op. */
export async function unlockWorktree(pi: ExtensionAPI, repoRoot: string, worktreeDir: string): Promise<void> {
	const result = await pi.exec("git", ["-C", repoRoot, "worktree", "unlock", worktreeDir], {
		timeout: LOCK_TIMEOUT_MS,
	});
	if (result.code !== 0 && !/not locked/i.test(result.stderr)) {
		throw new Error(`Failed to unlock worktree: ${result.stderr}`);
	}
}

/** Remove a worktree (unlocking first). `force` drops uncommitted changes. */
export async function removeWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	opts: { force?: boolean } = {},
): Promise<void> {
	await unlockWorktree(pi, repoRoot, worktreeDir).catch(() => {});
	const args = ["-C", repoRoot, "worktree", "remove", ...(opts.force ? ["--force"] : []), worktreeDir];
	const result = await pi.exec("git", args, { timeout: GIT_TIMEOUT_MS });
	if (result.code !== 0) {
		throw new Error(`Failed to remove worktree: ${result.stderr}`);
	}
}

/** Force-delete a branch. Idempotent — a missing branch is a no-op. Delete only after the
 *  worktree holding it is removed (a checked-out branch can't be deleted). */
export async function deleteBranch(pi: ExtensionAPI, repoRoot: string, branch: string): Promise<void> {
	const result = await pi.exec("git", ["-C", repoRoot, "branch", "-D", branch], { timeout: LOCK_TIMEOUT_MS });
	if (result.code !== 0 && !/not found|no branch/i.test(result.stderr)) {
		throw new Error(`Failed to delete branch: ${result.stderr}`);
	}
}

/**
 * Create a dispatched agent's own worktree, branched from `baseRef` (the parent's HEAD) on
 * a branch equal to `label` (`agent-<id>/<name>`), then lock it. Unlike `getOrCreateWorktree`,
 * this does NOT run `validateProtectedCheckout`: an agent worktree branches from the parent's
 * tree, not from a clean protected checkout.
 */
export async function createAgentWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	label: string,
	baseRef: string,
	lockReason = "basecamp agent run",
): Promise<WorktreeResult> {
	ensureWorktreeLabel(label);
	const worktreeDir = path.join(WORKTREES_ROOT, repoName, label);
	validateNoSymlinkedWorktreePath(worktreeDir);

	const records = await gitWorktreeRecords(pi, repoRoot);
	if (findWorktreeRecord(records, worktreeDir)) {
		throw new Error(`Agent worktree already registered: ${worktreeDir}`);
	}
	if (fs.existsSync(worktreeDir)) {
		throw new Error(`Worktree path exists but is not registered with git: ${worktreeDir}`);
	}

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });
	const result = await pi.exec("git", ["-C", repoRoot, "worktree", "add", "-b", label, worktreeDir, baseRef], {
		timeout: GIT_TIMEOUT_MS,
	});
	if (result.code !== 0) {
		throw new Error(`Failed to create agent worktree: ${result.stderr}`);
	}

	try {
		await lockWorktree(pi, repoRoot, worktreeDir, lockReason);
	} catch (error) {
		// Keep creation atomic: if the lock fails, remove the worktree (and its branch) we just
		// added so a partial failure doesn't leak an unreferenced tree that nothing reaps.
		await removeWorktree(pi, repoRoot, worktreeDir, { force: true }).catch(() => {});
		await deleteBranch(pi, repoRoot, label).catch(() => {});
		throw error;
	}
	return { worktreeDir, label, branch: label, created: true };
}
