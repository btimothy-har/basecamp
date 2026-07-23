/**
 * Transient-workspace provisioning for dispatched agents (issue #310, Phase 1).
 *
 * Every repo-backed run gets its own locked worktree; non-repo sessions provision nothing.
 * Branches are per-agent (`agent/<handle>`), worktrees per-run (`agent-<runToken>/<name>`):
 * a retask continues the agent's outstanding branch (or bases fresh once it was merged),
 * while an ask gets a detached checkout and never mints a branch. The base is the parent
 * worktree's HEAD — or a snapshot commit of its dirty state, so agents always see the
 * parent's WIP without the parent committing first.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	branchTip,
	createSnapshotCommit,
	detectDefaultBranch,
	gitOutput,
	isMergedInto,
	isWorktreeClean,
} from "../../git/repo.ts";
import { createAgentWorktree, deleteBranch, removeWorktree } from "../../git/worktrees/lifecycle.ts";
import { readWorktreeSetupCommand } from "../../host/config.ts";
import { runWorktreeSetup } from "../../project/workspace/setup.ts";
import type { WorkspaceState } from "../../project/workspace/state.ts";

export const AGENT_BRANCH_NAMESPACE = "agent/";

export function agentBranchName(agentHandle: string): string {
	return `${AGENT_BRANCH_NAMESPACE}${agentHandle}`;
}

export type AgentWorkspaceRequest =
	| {
			kind: "dispatch";
			/** Durable public handle keying the agent's branch. */
			agentHandle: string;
			/** Continuing an existing daemon-validated agent? Only retasks may continue a branch. */
			isRetask: boolean;
			runToken: string;
			agentName: string;
	  }
	| {
			kind: "ask";
			/** The ask target's handle — the answerer detaches at that agent's branch tip when it exists. */
			targetHandle: string;
			runToken: string;
			agentName: string;
	  };

export interface AgentWorkspaceProvision {
	worktreeDir: string;
	/** Worktree label (`agent-<runToken>/<name>`) — stamped on the child env pre-adoption. */
	label: string;
	/** The run's branch (`agent/<handle>`) — null for a detached ask workspace. */
	branch: string | null;
	/** Commit OID the run started from; teardown's zero-commit check compares against this. */
	baseOid: string;
	/** True when this provision minted the branch (teardown may delete it only then). */
	branchCreated: boolean;
	repoRoot: string;
	/** Nonfatal setup-hook failure, surfaced in the dispatch result. */
	setupWarning?: string;
}

function workspaceLabelName(name: string): string {
	const cleaned = name.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "");
	return cleaned || "agent";
}

async function resolveBaseOid(pi: ExtensionAPI, parentWorktree: string): Promise<string> {
	if (await isWorktreeClean(pi, parentWorktree)) {
		return await gitOutput(pi, parentWorktree, ["rev-parse", "HEAD"]);
	}
	return await createSnapshotCommit(pi, parentWorktree);
}

/** Best-effort integration candidates for the merged-branch check: parent branch + default. */
async function integrationBranches(pi: ExtensionAPI, repoRoot: string, parentWorktree: string): Promise<string[]> {
	const candidates = new Set<string>();
	try {
		const parentBranch = await gitOutput(pi, parentWorktree, ["branch", "--show-current"]);
		if (parentBranch) candidates.add(parentBranch);
	} catch {
		/* detached or unreadable parent — skip */
	}
	try {
		candidates.add(await detectDefaultBranch(pi, repoRoot));
	} catch {
		/* no recognizable default branch — skip */
	}
	return [...candidates];
}

async function resolveDispatchCheckout(
	pi: ExtensionAPI,
	request: Extract<AgentWorkspaceRequest, { kind: "dispatch" }>,
	repoRoot: string,
	parentWorktree: string,
): Promise<{ branch: string; baseOid: string; branchCreated: boolean; existing: boolean }> {
	const branch = agentBranchName(request.agentHandle);
	const tip = await branchTip(pi, repoRoot, branch);

	if (tip && !request.isRetask) {
		// A fresh dispatch must never adopt a pre-existing branch: the handle is new, so the
		// branch is stale residue (or a foreign collision) — refuse rather than continue it.
		throw new Error(
			`Branch ${branch} already exists but this is not a retask of that agent. ` +
				`Delete the stale branch (or merge it) and retry.`,
		);
	}

	if (tip) {
		for (const candidate of await integrationBranches(pi, repoRoot, parentWorktree)) {
			if (await isMergedInto(pi, repoRoot, branch, candidate)) {
				// Integrated: the work is in the candidate's history — start fresh from the parent.
				await deleteBranch(pi, repoRoot, branch);
				const baseOid = await resolveBaseOid(pi, parentWorktree);
				return { branch, baseOid, branchCreated: true, existing: false };
			}
		}
		// Outstanding: continue the agent's own branch so its memory and tree agree.
		return { branch, baseOid: tip, branchCreated: false, existing: true };
	}

	const baseOid = await resolveBaseOid(pi, parentWorktree);
	return { branch, baseOid, branchCreated: true, existing: false };
}

/**
 * Provision a dispatched run's own workspace. Returns null for a session without a repo
 * (nothing to isolate — the run keeps the launch cwd). Setup hooks run for dispatch runs
 * only (blocking, nonfatal); asks skip them for latency.
 */
export async function provisionAgentWorkspace(
	pi: ExtensionAPI,
	request: AgentWorkspaceRequest,
	workspace: WorkspaceState | null,
): Promise<AgentWorkspaceProvision | null> {
	const repo = workspace?.repo;
	if (!repo?.root || !repo.name) return null;

	const repoRoot = workspace?.protectedRoot ?? repo.root;
	const parentWorktree = workspace?.activeWorktree?.path ?? repoRoot;
	const label = `agent-${request.runToken}/${workspaceLabelName(request.agentName)}`;

	if (request.kind === "ask") {
		const targetTip = await branchTip(pi, repoRoot, agentBranchName(request.targetHandle));
		const baseOid = targetTip ?? (await resolveBaseOid(pi, parentWorktree));
		const worktree = await createAgentWorktree(pi, repoRoot, repo.name, label, { kind: "detached", baseRef: baseOid });
		return { worktreeDir: worktree.worktreeDir, label, branch: null, baseOid, branchCreated: false, repoRoot };
	}

	const checkout = await resolveDispatchCheckout(pi, request, repoRoot, parentWorktree);
	const worktree = await createAgentWorktree(
		pi,
		repoRoot,
		repo.name,
		label,
		checkout.existing
			? { kind: "existing-branch", branch: checkout.branch }
			: { kind: "new-branch", branch: checkout.branch, baseRef: checkout.baseOid },
	);

	const provision: AgentWorkspaceProvision = {
		worktreeDir: worktree.worktreeDir,
		label,
		branch: checkout.branch,
		baseOid: checkout.baseOid,
		branchCreated: checkout.branchCreated,
		repoRoot,
	};

	const setupCommand = readWorktreeSetupCommand(repo.name);
	if (setupCommand) {
		const result = await runWorktreeSetup(pi, { command: setupCommand, worktreeDir: worktree.worktreeDir, repoRoot });
		if (result.exitCode !== 0 || result.timedOut) {
			const reason = result.timedOut ? "timed out" : `exited ${result.exitCode}`;
			provision.setupWarning = `Workspace setup hook ${reason}: ${result.stderrTail || "(no stderr)"}`;
		}
	}

	return provision;
}

/**
 * Best-effort teardown of a just-provisioned workspace after a dispatch failure. Deletes the
 * branch only when this provision minted it — a retask's outstanding branch is prior work and
 * must survive a failed re-dispatch. The daemon owns teardown once a dispatch is accepted.
 */
export async function discardAgentWorkspace(
	pi: ExtensionAPI,
	provision: AgentWorkspaceProvision | null,
): Promise<void> {
	if (!provision) return;
	try {
		await removeWorktree(pi, provision.repoRoot, provision.worktreeDir, { force: true });
		if (provision.branch && provision.branchCreated) {
			await deleteBranch(pi, provision.repoRoot, provision.branch);
		}
	} catch {
		// best-effort; the daemon-restart reconcile and session-start sweep are the backstops.
	}
}
