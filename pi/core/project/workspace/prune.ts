/**
 * `/worktree prune` — manual removal of dormant session worktrees (issue #310 Phase 2).
 *
 * Branch GC is not automated in Phase 2: this picker is how a user reclaims session worktrees
 * (`wt-*`, `copilot/*`, direct labels) and, on explicit opt-in, their branches. Agent worktrees
 * are daemon-owned and never listed. A dirty worktree — or one holding a live lease or foreign
 * lock — is only force-removed after an explicit confirmation, so neither uncommitted work nor
 * another live session's workspace is discarded by surprise.
 */

import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { findWorktreeRecord, gitWorktreeRecords, listWorktrees } from "../../git/worktrees/crud.ts";
import { classifySessionWorktree, isWorktreeClean } from "../../git/worktrees/lease.ts";
import { deleteBranch, removeWorktree } from "../../git/worktrees/lifecycle.ts";
import { requireWorkspaceRuntime } from "./runtime.ts";

const AGENT_LABEL_RE = /^agent-[a-z0-9]+\//;

export interface PruneCandidate {
	label: string;
	path: string;
	branch: string | null;
	dirty: boolean;
	/** Fresh session lease or foreign lock — likely another live session's; confirm before removal. */
	inUse: boolean;
}

/** Session worktrees eligible for manual prune: under the repo's root, not agent-owned, not active. */
export async function collectPruneCandidates(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	activePath: string | null,
): Promise<PruneCandidate[]> {
	const summaries = await listWorktrees(pi, repoRoot, repoName);
	const records = await gitWorktreeRecords(pi, repoRoot);
	const candidates: PruneCandidate[] = [];
	for (const summary of summaries) {
		if (AGENT_LABEL_RE.test(summary.label)) continue;
		if (activePath && path.resolve(summary.path) === path.resolve(activePath)) continue;
		const record = findWorktreeRecord(records, summary.path);
		const dirty = !(await isWorktreeClean(pi, summary.path));
		candidates.push({
			label: summary.label,
			path: summary.path,
			branch: summary.branch === "detached" ? null : summary.branch,
			dirty,
			// The automated sweep only ever reaps "cold"; the picker may override, but never silently.
			inUse: record !== null && classifySessionWorktree(record) !== "cold",
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
	const marks = `${candidate.inUse ? "  (in use)" : ""}${candidate.dirty ? "  (uncommitted changes)" : ""}`;
	return `${candidate.label} — ${branch}${marks}`;
}

/**
 * Confirm and remove a chosen candidate. An in-use worktree (live lease or foreign lock) and a
 * dirty worktree are each force-removed only after an explicit confirmation (the guards against
 * yanking another live session's workspace or discarding uncommitted work via the picker);
 * the branch is deleted only on a further opt-in. Returns whether the worktree was removed.
 */
export async function confirmAndPrune(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	repoRoot: string,
	target: PruneCandidate,
): Promise<boolean> {
	if (target.inUse) {
		const proceed = await ctx.ui.confirm(
			"Worktree in use",
			`${target.label} appears to be in use by a live session. Remove it anyway?`,
		);
		if (!proceed) {
			ctx.ui.notify("Prune cancelled", "info");
			return false;
		}
	}

	if (target.dirty) {
		const proceed = await ctx.ui.confirm(
			"Uncommitted changes",
			`${target.label} has uncommitted changes that will be lost. Remove it anyway?`,
		);
		if (!proceed) {
			ctx.ui.notify("Prune cancelled", "info");
			return false;
		}
	}

	const deleteBranchToo =
		target.branch !== null && (await ctx.ui.confirm("Delete branch", `Also delete branch ${target.branch}?`));

	try {
		await pruneWorktree(pi, repoRoot, target, deleteBranchToo);
		ctx.ui.notify(
			`Pruned ${target.label}${deleteBranchToo ? ` and deleted ${target.branch}` : ` (branch ${target.branch ?? "none"} kept)`}`,
			"info",
		);
		return true;
	} catch (err) {
		ctx.ui.notify(`Prune failed: ${err instanceof Error ? err.message : String(err)}`, "error");
		return false;
	}
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

	await confirmAndPrune(pi, ctx, state.repo.root, target);
}
