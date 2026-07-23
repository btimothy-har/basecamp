/**
 * Worktree lifecycle primitives for dispatched agents.
 *
 * Pure git verbs (create-with-checkout, lock, unlock, remove) with no session state — the
 * confinement guard and the dispatch orchestration that use these live elsewhere.
 * `createAgentWorktree` materializes an agent's own worktree — on a new branch, an existing
 * branch, or detached — and locks it atomically; teardown at run end reclaims it.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../constants.ts";
import {
	ensureWorktreeLabel,
	findWorktreeRecord,
	gitWorktreeRecords,
	validateNoSymlinkedWorktreePath,
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

/** Remove a worktree, unlocking first unless disabled. `force` drops uncommitted changes. */
export async function removeWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	opts: { force?: boolean; unlock?: boolean } = {},
): Promise<void> {
	if (opts.unlock !== false) await unlockWorktree(pi, repoRoot, worktreeDir).catch(() => {});
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

/** How an agent worktree checks out: a fresh branch at a base, an existing branch, or detached. */
export type AgentCheckout =
	| { kind: "new-branch"; branch: string; baseRef: string }
	| { kind: "existing-branch"; branch: string }
	| { kind: "detached"; baseRef: string };

export interface AgentWorktreeResult {
	worktreeDir: string;
	label: string;
	/** The checked-out branch, or null for a detached workspace. */
	branch: string | null;
}

function checkoutArgs(checkout: AgentCheckout, worktreeDir: string): string[] {
	switch (checkout.kind) {
		case "new-branch":
			return ["-b", checkout.branch, worktreeDir, checkout.baseRef];
		case "existing-branch":
			return [worktreeDir, checkout.branch];
		case "detached":
			return ["--detach", worktreeDir, checkout.baseRef];
	}
}

export const AGENT_LOCK_REASON_PREFIX = "basecamp agent run";

/**
 * Create a dispatched agent's own worktree per `checkout`, then lock it. Unlike
 * `getOrCreateWorktree`, this does NOT run `validateProtectedCheckout`: an agent worktree
 * bases on the parent's tree, not on a clean protected checkout. Creation and locking use
 * one git command so no cleanup process can observe an unlocked live worktree.
 */
export async function createAgentWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	label: string,
	checkout: AgentCheckout,
	// The timestamp lets the session-start sweep age-gate provably-stale locked residue.
	lockReason = `${AGENT_LOCK_REASON_PREFIX} ${new Date().toISOString()}`,
): Promise<AgentWorktreeResult> {
	ensureWorktreeLabel(label);
	const worktreeDir = path.join(worktreesRoot(), repoName, label);
	validateNoSymlinkedWorktreePath(worktreeDir);

	const records = await gitWorktreeRecords(pi, repoRoot);
	if (findWorktreeRecord(records, worktreeDir)) {
		throw new Error(`Agent worktree already registered: ${worktreeDir}`);
	}
	if (fs.existsSync(worktreeDir)) {
		throw new Error(`Worktree path exists but is not registered with git: ${worktreeDir}`);
	}

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });
	const result = await pi.exec(
		"git",
		["-C", repoRoot, "worktree", "add", "--lock", "--reason", lockReason, ...checkoutArgs(checkout, worktreeDir)],
		{ timeout: GIT_TIMEOUT_MS },
	);
	if (result.code !== 0) {
		try {
			const partial = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), worktreeDir);
			if (partial) {
				await removeWorktree(pi, repoRoot, worktreeDir, { force: true }).catch(() => {});
				if (checkout.kind === "new-branch") await deleteBranch(pi, repoRoot, checkout.branch).catch(() => {});
			}
		} catch {
			// Git normally rolls back a failed atomic add; leave any unprovable residue untouched.
		}
		throw new Error(`Failed to create and lock agent worktree: ${result.stderr}`);
	}

	return { worktreeDir, label, branch: checkout.kind === "detached" ? null : checkout.branch };
}
