/**
 * Provisioning for a dispatched mutative agent's own worktree.
 *
 * A mutative agent works in its own worktree (`agent-<id>/<name>`), branched from the parent
 * worktree's HEAD, which it commits and the parent later integrates by merge. This is the
 * dispatch-side orchestration over the stateless `lifecycle.ts` primitives.
 * Read-only agents provision nothing.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { gitOutput } from "../../git/repo.ts";
import { createAgentWorktree, deleteBranch, removeWorktree } from "../../git/worktrees/lifecycle.ts";
import type { WorkspaceState } from "../../project/workspace/state.ts";
import type { AgentConfig } from "./discovery.ts";

export interface MutativeProvision {
	worktreeDir: string;
	/** The agent's branch (`agent-<id>/<name>`) — the deliverable the parent merges back. */
	branch: string;
	repoRoot: string;
}

/**
 * Provision a mutative agent's own worktree, branched from the parent worktree's HEAD (the
 * active worktree, or the protected checkout when none is active). Returns null for a
 * read-only agent. Throws with a clear message when a mutative agent cannot be provisioned
 * (no repo-backed session).
 *
 * The worktree/branch are keyed on `runToken` (a per-dispatch id), NOT the durable agent id:
 * the worktree's lifetime is per-run (created at dispatch, torn down at finish), so re-tasking
 * an agent gets a fresh worktree/branch rather than colliding with the prior run's.
 */
export async function provisionMutativeWorktree(
	pi: ExtensionAPI,
	agent: AgentConfig | null,
	runToken: string,
	workspace: WorkspaceState | null,
): Promise<MutativeProvision | null> {
	if (!agent || agent.readOnly) return null;

	const repo = workspace?.repo;
	if (!repo?.root || !repo.name) {
		throw new Error(`Mutative agent "${agent.name}" requires a repo-backed session (none is active).`);
	}

	const repoRoot = workspace?.protectedRoot ?? repo.root;
	const parentWorktree = workspace?.activeWorktree?.path ?? repoRoot;
	const baseRef = await gitOutput(pi, parentWorktree, ["rev-parse", "HEAD"], 15_000);
	const label = `agent-${runToken}/${agent.name}`;

	const worktree = await createAgentWorktree(pi, repoRoot, repo.name, label, baseRef);
	return { worktreeDir: worktree.worktreeDir, branch: worktree.branch, repoRoot };
}

/**
 * Best-effort teardown of a just-provisioned worktree after a dispatch failure. The
 * session-start orphan sweep is the backstop if this is skipped.
 */
export async function discardMutativeWorktree(pi: ExtensionAPI, provision: MutativeProvision | null): Promise<void> {
	if (!provision) return;
	try {
		// Remove the worktree, then delete its branch — nothing ran, so the branch is pure
		// clutter (the worktree must go first; a checked-out branch can't be deleted).
		await removeWorktree(pi, provision.repoRoot, provision.worktreeDir, { force: true });
		await deleteBranch(pi, provision.repoRoot, provision.branch);
	} catch {
		// best-effort; the orphan sweep will reap anything left.
	}
}
