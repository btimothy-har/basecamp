/**
 * Session-start sweep of finished agent workspaces — the last resort behind daemon-owned
 * teardown (run-exit reap and restart reconcile).
 *
 * Reclaims: unlocked agent worktrees whose branch is integrated; unlocked detached agent
 * worktrees (branchless report/ask residue); age-stale locked residue whose lock carries the
 * agent-run timestamp; and orphan agent branches with no worktree once integrated. Branches
 * carrying unintegrated commits always survive — deleting one is an explicit human act.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { AGENT_BRANCH_NAMESPACE, WORKTREES_ROOT } from "../constants.ts";
import { isMergedInto, tryGitOutput } from "../repo.ts";
import { gitWorktreeRecords } from "./crud.ts";
import { AGENT_LOCK_REASON_PREFIX, deleteBranch, removeWorktree, unlockWorktree } from "./lifecycle.ts";

// Legacy per-run branches require the full two-segment `agent-<token>/<name>` shape — a bare
// human `agent-*` branch is never agent residue.
const LEGACY_AGENT_BRANCH_RE = /^agent-[a-z0-9]+\//;
const AGENT_LABEL_DIR_RE = /^agent-[a-z0-9]+$/;
// Age is the sole staleness signal: a lock older than this (by its creation-time timestamp,
// never renewed) is treated as dead residue. There is no live-daemon cross-check — the daemon
// reap/reconcile chain is the primary owner, so this last-resort sweep only breaks locks the
// daemon left behind. The window is deliberately generous to avoid racing a long live run.
const STALE_LOCK_MS = 24 * 60 * 60 * 1000;

export interface AgentWorktreeSweepResult {
	removed: string[];
	kept: number;
}

function isAgentBranch(branch: string | null): branch is string {
	return (
		typeof branch === "string" && (branch.startsWith(AGENT_BRANCH_NAMESPACE) || LEGACY_AGENT_BRANCH_RE.test(branch))
	);
}

// Detached agent residue is identified by position, not pattern alone: exactly
// `<WORKTREES_ROOT>/<identity>/agent-<token>/<name>`, where Basecamp provisions agent
// workspaces. The identity is anchored explicitly (it may be one segment for a repo without a
// parseable origin remote, or `<org>/<repo>` otherwise), so the label must be exactly the
// two-segment `agent-<token>/<name>` shape relative to the identity root — a repo, org, or
// out-of-tree path that merely contains an `agent-…` segment is out of scope, and the reserved
// `agent-` label namespace keeps human worktrees from colliding.
function isAgentWorkspacePath(recordPath: string, identityRoot: string): boolean {
	const relative = path.relative(identityRoot, path.resolve(recordPath));
	if (relative.startsWith("..") || path.isAbsolute(relative)) return false;
	const segments = relative.split(path.sep);
	return segments.length === 2 && AGENT_LABEL_DIR_RE.test(segments[0] ?? "");
}

/** Age of an agent-run lock in ms, or null when the reason is absent/foreign/untimestamped. */
function agentLockAgeMs(lockReason: string | null, now: number): number | null {
	if (!lockReason?.startsWith(AGENT_LOCK_REASON_PREFIX)) return null;
	const timestamp = lockReason.slice(AGENT_LOCK_REASON_PREFIX.length).trim();
	const parsed = Date.parse(timestamp);
	return Number.isNaN(parsed) ? null : now - parsed;
}

async function isIntegrated(
	pi: ExtensionAPI,
	repoRoot: string,
	branch: string,
	integrationBranches: string[],
): Promise<boolean> {
	for (const candidate of integrationBranches) {
		if (await isMergedInto(pi, repoRoot, branch, candidate)) return true;
	}
	return false;
}

/** Orphan `agent/*` branches with no worktree: delete once integrated (they otherwise block
 *  a fresh dispatch minting the same handle). Unintegrated orphans are kept. */
async function sweepOrphanBranches(
	pi: ExtensionAPI,
	repoRoot: string,
	checkedOut: Set<string>,
	integrationBranches: string[],
): Promise<void> {
	const listed = await tryGitOutput(pi, repoRoot, ["branch", "--format=%(refname:short)"]);
	if (!listed) return;
	for (const branch of listed.split("\n").map((line) => line.trim())) {
		if (!isAgentBranch(branch) || checkedOut.has(branch)) continue;
		if (await isIntegrated(pi, repoRoot, branch, integrationBranches)) {
			await deleteBranch(pi, repoRoot, branch).catch(() => {});
		}
	}
}

/**
 * Remove reclaimable agent workspaces and integrated agent branches. Best-effort per record —
 * a failure on one never blocks the others.
 */
export async function sweepAgentWorktrees(
	pi: ExtensionAPI,
	repoRoot: string,
	identity: string,
): Promise<AgentWorktreeSweepResult> {
	const now = Date.now();
	const identityRoot = path.join(WORKTREES_ROOT, identity);
	const records = await gitWorktreeRecords(pi, repoRoot);
	const agentWorktrees = records.filter(
		(record) =>
			isAgentBranch(record.branch) || (record.branch === null && isAgentWorkspacePath(record.path, identityRoot)),
	);
	// Candidate integration targets: every non-agent branch (main, the parent's worktree, …).
	const integrationBranches = records
		.map((record) => record.branch)
		.filter((branch): branch is string => typeof branch === "string" && !isAgentBranch(branch));

	const removed: string[] = [];
	for (const record of agentWorktrees) {
		const integrated = record.branch ? await isIntegrated(pi, repoRoot, record.branch, integrationBranches) : false;
		// Reclaimable states: integrated branch, or branchless (detached report/ask residue).
		if (record.branch && !integrated) continue;

		if (record.locked) {
			const age = agentLockAgeMs(record.lockReason, now);
			// A live run holds the lock; only provably-stale agent locks may be broken.
			if (age === null || age < STALE_LOCK_MS) continue;
			await unlockWorktree(pi, repoRoot, record.path).catch(() => {});
		}

		try {
			// Force: agent workspaces are transient by contract — commits are the only durable
			// output, and this record's branch (if any) is already integrated.
			await removeWorktree(pi, repoRoot, record.path, { force: true, unlock: false });
		} catch {
			continue;
		}

		removed.push(record.path);
		if (record.branch) await deleteBranch(pi, repoRoot, record.branch).catch(() => {});
	}

	const checkedOut = new Set(records.map((record) => record.branch).filter((b): b is string => b !== null));
	await sweepOrphanBranches(pi, repoRoot, checkedOut, integrationBranches).catch(() => {});

	return { removed, kept: agentWorktrees.length - removed.length };
}
