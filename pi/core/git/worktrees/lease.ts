/**
 * Session-worktree leases and the session teardown matrix (issue #310 Phase 2).
 *
 * A session worktree is leased with a `git worktree lock` whose reason encodes the owning
 * pi session id and a "last active" timestamp: `basecamp session <sessionId> <ISO ts>`. The
 * lease is advisory — git already forbids two worktrees on one branch, and reaping only ever
 * removes a *clean* worktree — so ownership is the stable session id (never a pid) and
 * liveness is timestamp freshness. TypeScript owns this tier end-to-end; the daemon owns the
 * `basecamp agent run` tier separately.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { lockWorktree, removeWorktree, unlockWorktree } from "./lifecycle.ts";

export const SESSION_LOCK_REASON_PREFIX = "basecamp session ";
// A session lease older than this (never refreshed) reads as cold: its owner has quit or
// crashed. Generous by design so a long-lived idle session is rarely misjudged.
export const SESSION_COLD_TTL_MS = 24 * 60 * 60 * 1000;

const STATUS_TIMEOUT_MS = 15_000;

export interface SessionLease {
	sessionId: string;
	/** Epoch ms of the lease's last refresh. */
	timestamp: number;
}

export function sessionLeaseReason(sessionId: string, now: Date = new Date()): string {
	return `${SESSION_LOCK_REASON_PREFIX}${sessionId} ${now.toISOString()}`;
}

/** Parse a `basecamp session <id> <ts>` lock reason, or null when it is not a session lease. */
export function parseSessionLease(lockReason: string | null | undefined): SessionLease | null {
	if (!lockReason?.startsWith(SESSION_LOCK_REASON_PREFIX)) return null;
	const rest = lockReason.slice(SESSION_LOCK_REASON_PREFIX.length).trim();
	const separator = rest.indexOf(" ");
	if (separator <= 0) return null;
	const sessionId = rest.slice(0, separator);
	const timestamp = Date.parse(rest.slice(separator + 1).trim());
	if (!sessionId || Number.isNaN(timestamp)) return null;
	return { sessionId, timestamp };
}

/** True when a lock reason is a session lease owned by `sessionId`. */
export function leaseOwnedBy(lockReason: string | null | undefined, sessionId: string): boolean {
	const lease = parseSessionLease(lockReason);
	return lease !== null && lease.sessionId === sessionId;
}

/**
 * Acquire or refresh this session's lease on a worktree by (re)locking it with a fresh
 * timestamp. Git has no lock-reason update, so this unlocks then locks; the brief unlocked
 * window is harmless for an advisory lease. Throws only if the final lock fails.
 */
export async function acquireSessionLease(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	sessionId: string,
	now: Date = new Date(),
): Promise<void> {
	await unlockWorktree(pi, repoRoot, worktreeDir).catch(() => {});
	await lockWorktree(pi, repoRoot, worktreeDir, sessionLeaseReason(sessionId, now));
}

/** How the backstop sweep classifies a session worktree by its lease state. */
export type SessionWorktreeColdness = "live" | "cold" | "foreign";

/**
 * Classify a session worktree for the cold backstop:
 * - unlocked ⇒ `cold` (leaseless legacy/abandoned residue);
 * - session lease past the TTL ⇒ `cold` (owner quit or crashed);
 * - fresh session lease ⇒ `live` (skip);
 * - any non-session lock (e.g. an agent lock) ⇒ `foreign` (not ours to judge).
 */
export function classifySessionWorktree(
	record: { locked: boolean; lockReason: string | null },
	now: number = Date.now(),
	ttlMs: number = SESSION_COLD_TTL_MS,
): SessionWorktreeColdness {
	if (!record.locked) return "cold";
	const lease = parseSessionLease(record.lockReason);
	if (lease === null) return "foreign";
	return now - lease.timestamp >= ttlMs ? "cold" : "live";
}

/** True when a worktree has no uncommitted changes. Gitignored artifacts do not count. */
export async function isWorktreeClean(pi: ExtensionAPI, worktreeDir: string): Promise<boolean> {
	const result = await pi.exec("git", ["-C", worktreeDir, "status", "--porcelain"], {
		timeout: STATUS_TIMEOUT_MS,
	});
	return result.code === 0 && result.stdout.trim() === "";
}

export type SessionReapOutcome = "reaped" | "kept-dirty" | "error";

/**
 * Apply the session teardown matrix to one worktree: clean → remove it (the branch, the
 * durable artifact, is always kept); dirty → keep it untouched. `git worktree remove` runs
 * from `repoRoot` (the main checkout) since a worktree cannot remove its own cwd. The remove
 * uses `--force` only after `git status` proves the tree clean — so it reclaims gitignored
 * build artifacts (.venv, node_modules) while never discarding uncommitted work. Best-effort.
 */
export async function reapSessionWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
): Promise<SessionReapOutcome> {
	let clean: boolean;
	try {
		clean = await isWorktreeClean(pi, worktreeDir);
	} catch {
		return "error";
	}
	if (!clean) return "kept-dirty";
	try {
		await removeWorktree(pi, repoRoot, worktreeDir, { force: true, unlock: true });
	} catch {
		return "error";
	}
	return "reaped";
}
