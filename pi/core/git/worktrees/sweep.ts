/**
 * Session-start sweep of finished mutative-agent worktrees.
 *
 * A dispatched worker's worktree (`agent-<id>/<name>`) is reclaimed once its branch has been
 * integrated: when the branch is merged into a non-agent branch (the parent's worktree, main,
 * …), the work is preserved elsewhere, so the worktree + branch are safe to remove. A running
 * agent's branch is never merged, so it is never swept mid-run; an unmerged worktree is left
 * for the parent to integrate (docs/design/agent-isolation.md §4.5).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { gitWorktreeRecords } from "./crud.ts";
import { deleteBranch, removeWorktree } from "./lifecycle.ts";

const AGENT_BRANCH_PREFIX = "agent-";
const MERGE_CHECK_TIMEOUT_MS = 15_000;

export interface AgentWorktreeSweepResult {
	removed: string[];
	kept: number;
}

/** True if `branch` has been merged into `candidate` (is an ancestor of it). */
async function isMergedInto(pi: ExtensionAPI, repoRoot: string, branch: string, candidate: string): Promise<boolean> {
	const result = await pi.exec("git", ["-C", repoRoot, "merge-base", "--is-ancestor", branch, candidate], {
		timeout: MERGE_CHECK_TIMEOUT_MS,
	});
	return result.code === 0;
}

/**
 * Remove agent worktrees whose branch has been merged into a non-agent branch, deleting the
 * merged branch too. Best-effort per worktree — a failure on one never blocks the others, and
 * an unmerged agent worktree (still running, or awaiting integration) is left untouched.
 */
export async function sweepAgentWorktrees(pi: ExtensionAPI, repoRoot: string): Promise<AgentWorktreeSweepResult> {
	const records = await gitWorktreeRecords(pi, repoRoot);
	const agentWorktrees = records.filter((r) => r.branch?.startsWith(AGENT_BRANCH_PREFIX));
	// Candidate integration targets: every non-agent branch (main, the parent's worktree, …).
	const integrationBranches = records
		.map((r) => r.branch)
		.filter((b): b is string => typeof b === "string" && !b.startsWith(AGENT_BRANCH_PREFIX));

	const removed: string[] = [];
	for (const record of agentWorktrees) {
		const branch = record.branch;
		if (!branch) continue;

		let merged = false;
		for (const candidate of integrationBranches) {
			if (await isMergedInto(pi, repoRoot, branch, candidate)) {
				merged = true;
				break;
			}
		}
		if (!merged) continue;

		try {
			await removeWorktree(pi, repoRoot, record.path, { force: true });
			await deleteBranch(pi, repoRoot, branch);
			removed.push(record.path);
		} catch {
			// best-effort; leave it for the next sweep.
		}
	}

	return { removed, kept: agentWorktrees.length - removed.length };
}
