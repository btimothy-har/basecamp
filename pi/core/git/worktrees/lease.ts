/**
 * Session-worktree leases and the session teardown matrix (issue #310 Phase 2).
 *
 * A session worktree is leased with a `git worktree lock` whose reason encodes the owning
 * pi session id and a "last active" timestamp: `basecamp session <sessionId> <ISO ts>`. The
 * lease is advisory — git already forbids two worktrees on one branch, and reaping only ever
 * removes a *clean* worktree — so ownership is the stable session id (never a pid) and
 * liveness is timestamp freshness. TypeScript owns this tier end-to-end; the daemon owns the
 * `basecamp agent run` tier separately.
 *
 * A third lock class covers worktrees staged awaiting a session: `basecamp staged <ISO ts>`,
 * written by copilot's `launch_workstream` provisioning. A staged worktree has no owning
 * session yet, so without its own lock the cold sweep would read it as leaseless residue and
 * reap it before `pi --workstream` ever launches. The staged lock is take-over-able: a
 * session attaching the worktree breaks it and re-leases as its own. Its TTL is short —
 * staging means "launch now", so a staged worktree left unlaunched past the TTL reads as
 * cold again and is reclaimed.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { findWorktreeRecord, gitWorktreeRecords } from "./crud.ts";
import { lockWorktree, removeWorktree, unlockWorktree } from "./lifecycle.ts";

export const SESSION_LOCK_REASON_PREFIX = "basecamp session ";
// A session lease older than this (never refreshed) reads as cold: its owner has quit or
// crashed. Generous by design so a long-lived idle session is rarely misjudged.
export const SESSION_COLD_TTL_MS = 24 * 60 * 60 * 1000;

export const STAGED_LOCK_REASON_PREFIX = "basecamp staged ";
// A staged lock older than this reads as cold: the staged worktree was never launched.
// Deliberately much shorter than the session TTL — staging is "launch now", not parking.
export const SESSION_STAGED_TTL_MS = 60 * 60 * 1000;

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

export function stagedLockReason(now: Date = new Date()): string {
	return `${STAGED_LOCK_REASON_PREFIX}${now.toISOString()}`;
}

/** Parse a `basecamp staged <ts>` lock reason to its epoch-ms timestamp, or null. */
export function parseStagedLock(lockReason: string | null | undefined): number | null {
	if (!lockReason?.startsWith(STAGED_LOCK_REASON_PREFIX)) return null;
	const timestamp = Date.parse(lockReason.slice(STAGED_LOCK_REASON_PREFIX.length).trim());
	return Number.isNaN(timestamp) ? null : timestamp;
}

/** True when a lock reason is a session lease owned by `sessionId`. */
export function leaseOwnedBy(lockReason: string | null | undefined, sessionId: string): boolean {
	const lease = parseSessionLease(lockReason);
	return lease !== null && lease.sessionId === sessionId;
}

/**
 * Acquire or refresh this session's lease on a worktree by (re)locking it with a fresh
 * timestamp. A foreign lock — one that is neither a session lease nor a staged lock, e.g. the
 * daemon's `basecamp agent run` lock — is never overwritten: clobbering it would orphan the
 * worktree from its owner's teardown (the daemon breaks only provably-stale agent locks, and
 * the session sweep skips agent workspaces entirely), so a session that adopts or attaches
 * such a worktree simply runs unleased. A staged lock, by contrast, exists precisely to be
 * taken over: the session the worktree was staged for breaks it and re-leases as its own.
 * Git has no lock-reason update, so re-leasing unlocks then locks. That leaves a brief
 * unlocked window in which a *concurrent* session-start sweep could classify this worktree as
 * cold (leaseless) and, if it is also clean, reap it — a narrow race inherent to using the git
 * lock as the lease. It is bounded (two sequential git calls, victim is the live session
 * re-leasing) and never loses committed work; a stronger liveness signal is deferred hardening
 * (see AGENTS.md). Throws only if the final lock fails.
 */
export async function acquireSessionLease(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	sessionId: string,
	now: Date = new Date(),
): Promise<void> {
	const record = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), worktreeDir);
	if (record?.locked && parseSessionLease(record.lockReason) === null && parseStagedLock(record.lockReason) === null)
		return;
	await unlockWorktree(pi, repoRoot, worktreeDir).catch(() => {});
	await lockWorktree(pi, repoRoot, worktreeDir, sessionLeaseReason(sessionId, now));
}

/**
 * Stamp or refresh the staged lock on a worktree awaiting its session. A worktree already
 * held by a session lease or a foreign lock (e.g. the daemon's) is left untouched —
 * re-staging an adopted worktree must not clobber its owner's lease. Like re-leasing, the
 * unlock→lock refresh leaves a brief window in which a concurrent sweep could reap a clean
 * tree; bounded to one tool call and recoverable by re-running `launch_workstream`.
 */
export async function stageWorktreeLock(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	now: Date = new Date(),
): Promise<void> {
	const record = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), worktreeDir);
	if (record?.locked && parseStagedLock(record.lockReason) === null) return;
	await unlockWorktree(pi, repoRoot, worktreeDir).catch(() => {});
	await lockWorktree(pi, repoRoot, worktreeDir, stagedLockReason(now));
}

/** How the backstop sweep classifies a session worktree by its lease state. */
export type SessionWorktreeColdness = "live" | "cold" | "foreign";

/**
 * Classify a session worktree for the cold backstop:
 * - unlocked ⇒ `cold` (leaseless legacy/abandoned residue);
 * - session lease past the TTL ⇒ `cold` (owner quit or crashed);
 * - fresh session lease ⇒ `live` (skip);
 * - staged lock past the staged TTL ⇒ `cold` (staged but never launched);
 * - fresh staged lock ⇒ `live` (staged, awaiting its session);
 * - any other lock (e.g. an agent lock) ⇒ `foreign` (not ours to judge).
 */
export function classifySessionWorktree(
	record: { locked: boolean; lockReason: string | null },
	now: number = Date.now(),
	ttlMs: number = SESSION_COLD_TTL_MS,
	stagedTtlMs: number = SESSION_STAGED_TTL_MS,
): SessionWorktreeColdness {
	if (!record.locked) return "cold";
	const lease = parseSessionLease(record.lockReason);
	if (lease !== null) return now - lease.timestamp >= ttlMs ? "cold" : "live";
	const staged = parseStagedLock(record.lockReason);
	if (staged !== null) return now - staged >= stagedTtlMs ? "cold" : "live";
	return "foreign";
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

/**
 * Reap a worktree only when this session holds its lease. Confirms the worktree's lock reason
 * is a `basecamp session <sessionId>` lease owned by `sessionId` before applying the matrix —
 * so a fork or another live session's worktree (or an unowned/foreign lock) is never touched.
 * `repoRoot` is the main checkout. Returns `not-owned` when the ownership check fails.
 */
export async function reapOwnedSessionWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	worktreeDir: string,
	sessionId: string,
): Promise<SessionReapOutcome | "not-owned"> {
	const record = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), worktreeDir);
	if (!record || !leaseOwnedBy(record.lockReason, sessionId)) return "not-owned";
	return reapSessionWorktree(pi, repoRoot, worktreeDir);
}
