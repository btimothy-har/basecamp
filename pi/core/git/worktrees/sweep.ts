/**
 * Session-start sweep of finished agent workspaces — the backstop for runs whose daemon-side
 * teardown never fired (daemon died and has not restarted since).
 *
 * An agent worktree is reclaimed when its branch is integrated (merged into a non-agent
 * branch) or provably empty (its tip is still the dispatch snapshot commit — the run
 * committed nothing, and snapshot content is re-derivable from the parent's tree). Locked
 * worktrees are live and never touched. Branches carrying unintegrated real work survive.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isMergedInto, tryGitOutput } from "../repo.ts";
import { gitWorktreeRecords } from "./crud.ts";
import { deleteBranch, removeWorktree } from "./lifecycle.ts";

// Legacy per-run branches (`agent-<token>/<name>`) and per-agent branches (`agent/<handle>`).
const AGENT_BRANCH_PREFIXES = ["agent-", "agent/"];
const SNAPSHOT_COMMIT_SUBJECT = "basecamp dispatch snapshot";

export interface AgentWorktreeSweepResult {
	removed: string[];
	kept: number;
}

function isAgentBranch(branch: string | null): branch is string {
	return typeof branch === "string" && AGENT_BRANCH_PREFIXES.some((prefix) => branch.startsWith(prefix));
}

/** True when the branch tip is still the dispatch snapshot commit — the run committed nothing. */
async function isSnapshotOnly(pi: ExtensionAPI, repoRoot: string, branch: string): Promise<boolean> {
	const subject = await tryGitOutput(pi, repoRoot, ["log", "-1", "--format=%s", branch]);
	return subject === SNAPSHOT_COMMIT_SUBJECT;
}

/**
 * Remove agent worktrees whose branch is integrated or snapshot-only, deleting the branch
 * too. Best-effort per worktree — a failure on one never blocks the others, and an agent
 * worktree with outstanding committed work is left untouched.
 */
export async function sweepAgentWorktrees(pi: ExtensionAPI, repoRoot: string): Promise<AgentWorktreeSweepResult> {
	const records = await gitWorktreeRecords(pi, repoRoot);
	const agentWorktrees = records.filter((record) => isAgentBranch(record.branch));
	// Candidate integration targets: every non-agent branch (main, the parent's worktree, …).
	const integrationBranches = records
		.map((record) => record.branch)
		.filter((branch): branch is string => typeof branch === "string" && !isAgentBranch(branch));

	const removed: string[] = [];
	for (const record of agentWorktrees) {
		const branch = record.branch;
		if (!branch || record.locked) continue;

		let reclaimable = await isSnapshotOnly(pi, repoRoot, branch);
		if (!reclaimable) {
			for (const candidate of integrationBranches) {
				if (await isMergedInto(pi, repoRoot, branch, candidate)) {
					reclaimable = true;
					break;
				}
			}
		}
		if (!reclaimable) continue;

		try {
			await removeWorktree(pi, repoRoot, record.path, { unlock: false });
		} catch {
			continue;
		}

		removed.push(record.path);
		await deleteBranch(pi, repoRoot, branch).catch(() => {});
	}

	return { removed, kept: agentWorktrees.length - removed.length };
}
