/**
 * Session-worktree cold backstop (issue #310 Phase 2).
 *
 * The primary teardown is exit-reap at `session_shutdown`. This session-start sweep is the
 * backstop for the crash case (no graceful quit fired) and for leaseless legacy residue: it
 * reclaims session worktrees (`wt-*`, `copilot/*`, direct labels) that are cold — a session
 * lease past the TTL, or unlocked/leaseless — AND clean. Dirty-cold worktrees are surfaced,
 * never removed; the branch is always kept. Agent worktrees are the daemon's, never touched
 * here. Strictly local (git status only, no network).
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { AGENT_BRANCH_NAMESPACE, worktreesRoot } from "../constants.ts";
import { type GitWorktreeRecord, gitWorktreeRecords } from "./crud.ts";
import { classifySessionWorktree, reapSessionWorktree } from "./lease.ts";

const LEGACY_AGENT_BRANCH_RE = /^agent-[a-z0-9]+\//;
const AGENT_LABEL_DIR_RE = /^agent-[a-z0-9]+$/;

export interface SessionSweepResult {
	/** Cold+clean worktrees removed (branch kept). */
	reclaimed: string[];
	/** Cold+dirty worktrees kept and surfaced for manual `/worktree prune`. */
	surfaced: string[];
	/** Live (fresh-leased), foreign-locked, or errored worktrees left in place. */
	kept: number;
}

function isAgentBranch(branch: string | null): boolean {
	return branch !== null && (branch.startsWith(AGENT_BRANCH_NAMESPACE) || LEGACY_AGENT_BRANCH_RE.test(branch));
}

/**
 * True when a record is a session worktree under `<WORKTREES_ROOT>/<identity>`: a direct label
 * (one segment) or a nested `<namespace>/<name>` (two segments) whose first segment is not an
 * `agent-<token>` label. The main checkout (outside the root) and agent workspaces are excluded.
 */
function isSessionWorktree(recordPath: string, identityRoot: string): boolean {
	const relative = path.relative(identityRoot, path.resolve(recordPath));
	if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return false;
	const segments = relative.split(path.sep);
	if (segments.length < 1 || segments.length > 2) return false;
	return !AGENT_LABEL_DIR_RE.test(segments[0] ?? "");
}

/**
 * Reclaim cold+clean session worktrees for one repo. Best-effort per record — a failure on one
 * never blocks the others. `identity` is the repo's `<org>/<name>` (or bare) identity.
 */
export async function sweepSessionWorktrees(
	pi: ExtensionAPI,
	repoRoot: string,
	identity: string,
	now: number = Date.now(),
): Promise<SessionSweepResult> {
	const identityRoot = path.join(worktreesRoot(), identity);
	const result: SessionSweepResult = { reclaimed: [], surfaced: [], kept: 0 };

	let records: GitWorktreeRecord[];
	try {
		records = await gitWorktreeRecords(pi, repoRoot);
	} catch {
		return result;
	}

	for (const record of records) {
		if (isAgentBranch(record.branch) || !isSessionWorktree(record.path, identityRoot)) continue;
		if (classifySessionWorktree(record, now) !== "cold") {
			result.kept += 1;
			continue;
		}
		const outcome = await reapSessionWorktree(pi, repoRoot, record.path);
		if (outcome === "reaped") result.reclaimed.push(record.path);
		else if (outcome === "kept-dirty") result.surfaced.push(record.path);
		else result.kept += 1;
	}

	return result;
}
