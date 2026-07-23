/**
 * `/worktree prune` — manual removal of dormant session worktrees (issue #310 Phase 2).
 *
 * Branch GC is not automated in Phase 2: this picker is how a user reclaims session worktrees
 * (`wt-*`, `copilot/*`, direct labels) and, on explicit opt-in, their branches. Agent worktrees
 * are daemon-owned and never listed. A dirty worktree is only force-removed after an explicit
 * confirmation, so uncommitted work is never discarded by surprise.
 */

import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { listWorktrees } from "../../git/worktrees/crud.ts";
import { isWorktreeClean } from "../../git/worktrees/lease.ts";
import { deleteBranch, removeWorktree } from "../../git/worktrees/lifecycle.ts";
import { requireWorkspaceRuntime } from "./runtime.ts";

const AGENT_LABEL_RE = /^agent-[a-z0-9]+\//;

export interface PruneCandidate {
	label: string;
	path: string;
	branch: string | null;
	dirty: boolean;
}

/** Session worktrees eligible for manual prune: under the repo's root, not agent-owned, not active. */
export async function collectPruneCandidates(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	activePath: string | null,
): Promise<PruneCandidate[]> {
	const summaries = await listWorktrees(pi, repoRoot, repoName);
	const candidates: PruneCandidate[] = [];
	for (const summary of summaries) {
		if (AGENT_LABEL_RE.test(summary.label)) continue;
		if (activePath && path.resolve(summary.path) === path.resolve(activePath)) continue;
		const dirty = !(await isWorktreeClean(pi, summary.path));
		candidates.push({
			label: summary.label,
			path: summary.path,
			branch: summary.branch === "detached" ? null : summary.branch,
			dirty,
		});
	}
	return candidates;
}

/** Force-remove a selected worktree; delete its branch only on explicit opt-in. */
export async function pruneWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	target: PruneCandidate,
	deleteBranchToo: boolean,
): Promise<void> {
	await removeWorktree(pi, repoRoot, target.path, { force: true, unlock: true });
	if (deleteBranchToo && target.branch) await deleteBranch(pi, repoRoot, target.branch);
}

function formatCandidate(candidate: PruneCandidate): string {
	const branch = candidate.branch ?? "detached";
	return `${candidate.label} — ${branch}${candidate.dirty ? "  (uncommitted changes)" : ""}`;
}

export async function runWorktreePrune(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const state = requireWorkspaceRuntime().current();
	if (!state?.repo) {
		ctx.ui.notify("/worktree prune requires a git repository", "error");
		return;
	}
	if (!ctx.hasUI) return;

	const candidates = await collectPruneCandidates(
		pi,
		state.repo.root,
		state.repo.name,
		state.activeWorktree?.path ?? null,
	);
	if (candidates.length === 0) {
		ctx.ui.notify(`No prunable worktrees for ${state.repo.name}`, "info");
		return;
	}

	const byChoice = new Map(candidates.map((c) => [formatCandidate(c), c]));
	const choice = await ctx.ui.select("Prune a worktree (its branch is kept unless you confirm)", [...byChoice.keys()]);
	const target = choice ? byChoice.get(choice) : undefined;
	if (!target) {
		ctx.ui.notify("Prune cancelled", "info");
		return;
	}

	if (target.dirty) {
		const proceed = await ctx.ui.confirm(
			"Uncommitted changes",
			`${target.label} has uncommitted changes that will be lost. Remove it anyway?`,
		);
		if (!proceed) {
			ctx.ui.notify("Prune cancelled", "info");
			return;
		}
	}

	const deleteBranchToo =
		target.branch !== null && (await ctx.ui.confirm("Delete branch", `Also delete branch ${target.branch}?`));

	try {
		await pruneWorktree(pi, state.repo.root, target, deleteBranchToo);
		ctx.ui.notify(
			`Pruned ${target.label}${deleteBranchToo ? ` and deleted ${target.branch}` : ` (branch ${target.branch ?? "none"} kept)`}`,
			"info",
		);
	} catch (err) {
		ctx.ui.notify(`Prune failed: ${err instanceof Error ? err.message : String(err)}`, "error");
	}
}
